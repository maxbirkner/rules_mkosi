"""Patches mkosi v27 internals so that a release build reads only declared inputs and is reproducible.

mkosi has no options for these constraints, so its functions are replaced in the release child process, which runs
mkosi in-process.
"""

import os
from dataclasses import replace
from pathlib import Path

from . import release_sandbox, tree
from .release_validation import (
    is_declared,
    release_apt_components,
    validate_ini_section,
    validate_release_configuration,
)

_IN_SANDBOX_REPOSITORY = "/repository"


def activate_release_mode(mirror, settings, allowed_paths, allowed_extra_tree):
    """Patches mkosi for a release build of settings.stage.

    A finalize stage has no mirror: it installs no packages and reads only the declared base tree and initrd.
    """
    import mkosi
    import mkosi.distribution.debian

    if (mirror is None) != (settings.stage == "finalize"):
        raise SystemExit("only the release finalize stage runs without the Debian snapshot mirror")
    if mirror is not None:
        _serve_local_mirror(os.fspath(mirror), settings.components)
    _ConfigurationValidator(settings, allowed_paths, allowed_extra_tree).install()
    mkosi.distribution.debian.install_apt_sources = _remove_apt_sources
    mkosi.install_sandbox_trees = _install_sandbox_trees
    if settings.stage == "base":
        # The base root crosses Bazel's cache as an archive, so its bytes must depend only on the tree.
        mkosi.make_tar = deterministic_make_tar


def _serve_local_mirror(mirror, components):
    """Mounts the long Bazel mirror path read-only at mkosi's stable in-sandbox repository path.

    mkosi v27 registers a local mirror with only the main component. The snapshot can stage more components, so the
    mirror source instead lists main plus the components requested through Repositories=, each of which must be
    present in the snapshot.
    """
    from mkosi.context import Context
    from mkosi.distribution.debian import Installer
    from mkosi.installer import PackageManager

    _patch_repositories(Installer, "file://" + mirror, components)
    _patch_mounts(PackageManager, mirror)
    _patch_context_repository(Context, mirror)


def _patch_repositories(installer, source_url, components):
    original = installer.repositories.__func__

    def repositories(cls, context, for_image=False):
        if for_image:
            return
        for repository in original(cls, context, for_image):
            if repository.url == source_url:
                repository = replace(
                    repository,
                    url="file://" + _IN_SANDBOX_REPOSITORY,
                    components=release_apt_components(context.config.repositories, components),
                )
            yield repository

    installer.repositories = classmethod(repositories)


def _patch_mounts(package_manager, mirror):
    original = package_manager.mounts.__func__

    def mounts(cls, context):
        options = original(cls, context)
        repository = _find_bind(options, "--bind", mirror, _IN_SANDBOX_REPOSITORY)
        if repository is None:
            raise SystemExit("mkosi did not register the declared release mirror")
        options[repository] = "--ro-bind"
        duplicate = _find_bind(options, "--ro-bind", mirror, mirror)
        if duplicate is not None:
            del options[duplicate : duplicate + 3]
        return options

    package_manager.mounts = classmethod(mounts)


def _find_bind(options, kind, source, destination):
    for index in range(len(options) - 2):
        if (
            options[index] == kind
            and os.fspath(options[index + 1]) == source
            and os.fspath(options[index + 2]) == destination
        ):
            return index
    return None


def _patch_context_repository(context_class, mirror):
    original_init = context_class.__init__

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._rules_mkosi_release_mirror = True

    # Context.__init__ creates the workspace repository directory, so the mirror replaces it only afterwards.
    def repository(self):
        if not getattr(self, "_rules_mkosi_release_mirror", False):
            return self.workspace / "repository"
        return Path(mirror)

    context_class.__init__ = init
    context_class.repository = property(repository)


class _ConfigurationValidator:
    """Validates the first configuration that mkosi parses for the requested image, and the INI files it reads."""

    def __init__(self, settings, allowed_paths, allowed_extra_tree):
        import mkosi.config

        self._config_module = mkosi.config
        self._original_parse_config = mkosi.config.parse_config
        self._original_parse_ini = mkosi.config.parse_ini
        self._settings = settings
        self._allowed_paths = allowed_paths
        self._allowed_extra_tree = allowed_extra_tree
        self._declared_roots = tuple(Path(path).resolve() for path in allowed_paths)
        self._pending = True
        self._depth = 0

    def install(self):
        self._config_module.parse_config = self.parse_config
        self._config_module.parse_ini = self.parse_ini

    def parse_config(self, *args, **kwargs):
        # mkosi parses its bundled mkosi-initrd configuration separately; that pinned resource is not caller input.
        primary = "mkosi-initrd" not in os.fspath(kwargs.get("resources", "/"))
        self._depth += 1
        try:
            parsed = self._original_parse_config(*args, **kwargs)
        finally:
            self._depth -= 1
        if self._pending and self._depth == 0 and primary:
            parsed = self._validated(parsed)
            self._pending = False
        return parsed

    def _validated(self, parsed):
        images = tuple(_without_proxy_certificates(config) for config in parsed[2])
        validate_release_configuration(
            tuple(config for config in images if getattr(config, "image", "main") == "main"),
            self._settings,
            self._allowed_paths,
            self._allowed_extra_tree,
        )
        return (parsed[0], parsed[1], images)

    def parse_ini(self, *args, **kwargs):
        path = Path(args[0]).resolve() if args else None
        declared = path is not None and is_declared(path, self._declared_roots)
        for section, setting, value in self._original_parse_ini(*args, **kwargs):
            if self._pending and self._depth == 1 and declared:
                validate_ini_section(section)
            yield section, setting, value


def _without_proxy_certificates(config):
    # mkosi defaults ProxyPeerCertificate= to a host CA bundle; a release build uses no proxy, so it needs none.
    return replace(config, proxy_peer_certificate=None, proxy_client_certificate=None, proxy_client_key=None)


def _remove_apt_sources(context, repositories):
    """Leaves the image without APT sources, because the release mirror exists only during the build."""
    del repositories
    apt = context.root / "etc/apt"
    (apt / "sources.list").unlink(missing_ok=True)
    sources = apt / "sources.list.d"
    if sources.exists():
        for source in sources.iterdir():
            if source.is_file() and source.suffix in (".list", ".sources"):
                source.unlink()


_SANDBOX_DIRECTORIES = (
    "etc/pki/ca-trust",
    "etc/pki/tls",
    "etc/ssl",
    "etc/ca-certificates",
    "etc/pacman.d/gnupg",
    "etc/alternatives",
)
_SANDBOX_PLACEHOLDER_FILES = ("etc/shadow", "etc/gshadow", "etc/ld.so.cache")


def _install_sandbox_trees(config, dst):
    """Mirrors mkosi v27's install_sandbox_trees, but copies no host files and resolves host names only locally."""
    (dst / "etc").mkdir(exist_ok=True)
    _install_crypto_policy(config, dst)
    _install_configured_sandbox_trees(config, dst)
    if not (dst / "etc/mtab").is_symlink():
        (dst / "etc/mtab").symlink_to("../proc/self/mounts")
    (dst / "etc/resolv.conf").unlink(missing_ok=True)
    (dst / "etc/resolv.conf").touch()
    if not (dst / "etc/nsswitch.conf").exists():
        tree.write_file(dst / "etc/nsswitch.conf", release_sandbox.NSSWITCH)
    _link_tools_static(config, dst)
    for directory in _SANDBOX_DIRECTORIES:
        (dst / directory).mkdir(parents=True, exist_ok=True)
    for filename in _SANDBOX_PLACEHOLDER_FILES:
        (dst / filename).touch(exist_ok=True)


def _install_crypto_policy(config, dst):
    import mkosi

    policy = config.tools() / "usr/share/crypto-policies/back-ends/DEFAULT"
    if policy.exists():
        (dst / "etc/crypto-policies").mkdir(exist_ok=True)
        mkosi.copy_tree(policy, dst / "etc/crypto-policies/back-ends", sandbox=config.sandbox)


def _install_configured_sandbox_trees(config, dst):
    import mkosi

    if config.sandbox_trees:
        with mkosi.complete_step("Copying in sandbox trees…"):
            for sandbox_tree in config.sandbox_trees:
                mkosi.install_tree(config, sandbox_tree.source, dst, target=sandbox_tree.target, preserve=False)


def _link_tools_static(config, dst):
    (dst / "etc/static").unlink(missing_ok=True)
    if (config.tools() / "etc/static").is_symlink():
        (dst / "etc/static").symlink_to((config.tools() / "etc/static").readlink())


def deterministic_make_tar(src, dst, *, sandbox=None):
    """Archives a root like mkosi v27's make_tar, but with a reproducible member order.

    mkosi's archive follows directory order, which depends on the file system. Sorting by name and not probing for
    holes makes the archive bytes depend only on the tree.
    """
    from mkosi.archive import tar_exclude_apivfs_tmp
    from mkosi.log import complete_step
    from mkosi.run import finalize_passwd_symlinks, nosandbox, run, workdir

    sandbox = sandbox or nosandbox
    root = workdir(src, sandbox)
    with complete_step("Creating reproducible tar archive {}…".format(dst)):
        with dst.open("wb") as archive:
            run(
                tar_command(root, tar_exclude_apivfs_tmp(), os.getuid()),
                stdout=archive,
                sandbox=sandbox(options=["--ro-bind", src, root, *finalize_passwd_symlinks(root)]),
            )


def tar_command(root, excludes, uid):
    ownership = ["--owner=root:0", "--group=root:0"] if uid != 0 else []
    return [
        "tar",
        "--create",
        "--file",
        "-",
        "--directory",
        root,
        "--sort=name",
        "--acls",
        "--selinux",
        "--xattrs",
        "--pax-option=delete=atime,delete=ctime,delete=mtime",
        "--force-local",
        *ownership,
        *excludes,
        ".",
    ]
