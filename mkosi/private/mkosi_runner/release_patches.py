"""Patches mkosi v27 internals so that a release build reads only declared inputs and is reproducible.

Where mkosi has no option for a constraint, its functions are replaced in the release child process, which runs mkosi
in-process. mkosi_contract.py pins the patched internals of each supported mkosi version, and release mode fails before
patching a different mkosi. The APT sources of the Debian snapshot mirror use mkosi's documented sandbox tree override
instead of a patch.
"""

import datetime
import hashlib
import hmac
import os
import uuid
from collections.abc import Callable, Iterator, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, TypeAlias

from . import mkosi_contract, release_sandbox, tree
from .mkosi_contract import MkosiConfig, MkosiObject
from .release_validation import (
    ReleaseSettings,
    is_declared,
    release_apt_components,
    validate_architecture,
    validate_ini_section,
    validate_release_configuration,
)

# The (args, tools, images) that mkosi.config.parse_config() returns.
_ParsedConfig: TypeAlias = tuple[MkosiObject, MkosiObject, Sequence[MkosiConfig]]


def activate_release_mode(
    mirror: release_sandbox.SnapshotMirror | None,
    settings: ReleaseSettings,
    allowed_paths: Sequence[str],
    allowed_extra_tree: Path | None,
) -> None:
    """Patches mkosi for a release build of settings.stage.

    A finalize stage has no mirror: it installs no packages and reads only the declared base tree and initrd.
    """
    import mkosi.distribution.debian

    upstream = mkosi_contract.upstream_mkosi()
    mkosi_contract.verify()
    if (mirror is None) != (settings.stage == "finalize"):
        raise SystemExit("only the release finalize stage runs without the Debian snapshot mirror")
    if mirror is not None:
        _serve_mirror(mirror)
    _ConfigurationValidator(settings, allowed_paths, allowed_extra_tree, mirror).install()
    require_selected_devicetrees(Path(settings.devicetrees) if settings.devicetrees else None)
    mkosi.distribution.debian.install_apt_sources = _remove_apt_sources
    upstream.install_sandbox_trees = _install_sandbox_trees
    if settings.stage == "base":
        # The base root crosses Bazel's cache as an archive, so its bytes must depend only on the tree.
        upstream.make_tar = deterministic_make_tar
    if settings.stage == "finalize":
        include_base_packages_in_manifest()


def activate_snapshot_mirror(
    mirror: release_sandbox.SnapshotMirror, components: Sequence[str], architecture: str
) -> None:
    """Patches mkosi so that a tracer build installs packages only from the Debian snapshot mirror.

    The configuration must resolve Architecture= to the snapshot's Debian architecture.
    """
    mkosi_contract.verify()
    _serve_mirror(mirror)
    _MirrorConfiguration(mirror, components, architecture).install()


def include_base_packages_in_manifest() -> None:
    """Lists the packages of the base tree in the manifest of a finalized image.

    With BaseTrees=, mkosi v27 omits packages installed before the build started from the manifest. Finalization
    installs no packages, so that would leave the manifest empty; every package of the image comes from the base.
    """
    from mkosi.manifest import Manifest

    original = Manifest.record_deb_packages

    def record_deb_packages(self: MkosiObject) -> None:
        self._init_timestamp = datetime.datetime.min
        original(self)

    Manifest.record_deb_packages = record_deb_packages


# The prefix of the Devicetrees= entries that with_label_devicetrees appends for the device trees of
# mkosi_image(devicetrees = ...). mkosi only selects device trees if Devicetrees= is not empty, and
# require_selected_devicetrees replaces these entries with the files instead of matching them against the image tree.
LABEL_DEVICETREES = "rules-mkosi-label:"


def require_selected_devicetrees(label_devicetrees: Path | None = None) -> None:
    """Fails the build if a Devicetrees= pattern selects no device tree of the image's kernel.

    mkosi v27 only warns when its patterns select nothing, and silently drops a pattern that matches no file, so a
    typo or a kernel package that moved its device trees would build a UKI without them.

    The entries of with_label_devicetrees select the files in label_devicetrees, ahead of the device trees that the
    patterns select in the image tree. They are returned as absolute paths, which build_uki reads as they are, because
    it joins each path to the image tree, so the files reach only the UKI and never the image tree, from which mkosi
    fills the root, the ESP and the other partitions and outputs.
    """
    upstream = mkosi_contract.upstream_mkosi()
    original = upstream.filter_devicetrees

    def filter_devicetrees(root: Path, kver: str, *, include: Sequence[str]) -> list[Path]:
        labels = [
            (label_devicetrees / entry[len(LABEL_DEVICETREES) :]).resolve()
            for entry in include
            if label_devicetrees is not None and entry.startswith(LABEL_DEVICETREES)
        ]
        patterns = [entry for entry in include if not entry.startswith(LABEL_DEVICETREES)]
        selected = original(root, kver, include=patterns) if patterns else []
        unselected = [
            pattern
            for pattern in patterns
            if not pattern.startswith("-") and not set(original(root, kver, include=[pattern])) & set(selected)
        ]
        if unselected or not (selected or labels):
            subject = "pattern {} selects".format(unselected[0]) if unselected else "selects"
            raise SystemExit(
                "release configuration Devicetrees= {} no device tree of kernel {}; mkosi selects .dtb files below "
                "usr/lib/modules/{}/dtb/, usr/lib/firmware/{}/device-tree/ and usr/lib/linux-image-{}/ of the image, "
                "and the last matching pattern wins".format(subject, kver, kver, kver, kver)
            )
        return [*labels, *selected]

    upstream.filter_devicetrees = filter_devicetrees


def with_label_devicetrees(images: tuple[MkosiConfig, ...], label_devicetrees: Path | None) -> tuple[MkosiConfig, ...]:
    """Returns images with Devicetrees= entries for the device trees of mkosi_image(devicetrees = ...).

    Only the main image has a UKI.
    """
    if label_devicetrees is None:
        return images
    entries = [LABEL_DEVICETREES + source.name for source in sorted(label_devicetrees.iterdir())]
    return tuple(
        replace(config, devicetrees=[*config.devicetrees, *entries])
        if getattr(config, "image", "main") == "main"
        else config
        for config in images
    )


def _serve_mirror(mirror: release_sandbox.SnapshotMirror) -> None:
    """Mounts the snapshot mirror read-only at mkosi's stable in-sandbox repository path, /repository.

    mkosi maps the /repository paths of the debs that it bootstraps a Debian root from to Context.repository, so the
    mirror replaces that local package repository instead of being mounted elsewhere.
    """
    from mkosi.context import Context
    from mkosi.installer import PackageManager

    directory = os.fspath(mirror.directory)
    _patch_mounts(PackageManager, directory)
    _patch_context_repository(Context, directory)


def _write_mirror_sources(
    mirror: release_sandbox.SnapshotMirror, images: Sequence[MkosiConfig], components: Sequence[str]
) -> None:
    """Lists the mirror in APT sources for the suite and the Repositories= of the parsed images.

    The sources list main plus the components requested through Repositories=, each of which must be present in the
    snapshot. Both settings are universal, so every image of the build uses the same sources.
    """
    if not images:
        raise SystemExit("mkosi parsed no image to install from the Debian snapshot mirror")
    config = images[0]
    mirror.write_sources(config.release, release_apt_components(config.repositories, components))


def _patch_mounts(package_manager: type[Any], mirror: str) -> None:
    original = package_manager.mounts.__func__

    def mounts(cls: type[Any], context: MkosiObject) -> list[str | os.PathLike[str]]:
        options = original(cls, context)
        repository = _find_bind(options, "--bind", mirror, "/repository")
        if repository is None:
            raise SystemExit("mkosi did not register the declared release mirror")
        options[repository] = "--ro-bind"
        return options

    package_manager.mounts = classmethod(mounts)


def _find_bind(options: Sequence[str | os.PathLike[str]], kind: str, source: str, destination: str) -> int | None:
    for index in range(len(options) - 2):
        if (
            options[index] == kind
            and os.fspath(options[index + 1]) == source
            and os.fspath(options[index + 2]) == destination
        ):
            return index
    return None


def _patch_context_repository(context_class: type[Any], mirror: str) -> None:
    original_init = context_class.__init__

    def init(self: MkosiObject, *args: MkosiObject, **kwargs: MkosiObject) -> None:
        original_init(self, *args, **kwargs)
        self._rules_mkosi_release_mirror = True

    # Context.__init__ creates the workspace repository directory, so the mirror replaces it only afterwards.
    def repository(self: MkosiObject) -> Path:
        if not getattr(self, "_rules_mkosi_release_mirror", False):
            return self.workspace / "repository"
        return Path(mirror)

    context_class.__init__ = init
    context_class.repository = property(repository)


class _FirstConfiguration:
    """Wraps mkosi's parse_config to act once on the first configuration that it parses for the requested image."""

    def __init__(self) -> None:
        import mkosi.config

        self._config_module = mkosi.config
        self._original_parse_config = mkosi.config.parse_config
        self._pending = True
        self._depth = 0

    def install(self) -> None:
        self._config_module.parse_config = self.parse_config

    def parse_config(self, *args: MkosiObject, **kwargs: MkosiObject) -> _ParsedConfig:
        # mkosi parses its bundled mkosi-initrd configuration separately; that pinned resource is not caller input.
        primary = "mkosi-initrd" not in os.fspath(kwargs.get("resources", "/"))
        self._depth += 1
        try:
            parsed = self._original_parse_config(*args, **kwargs)
        finally:
            self._depth -= 1
        if self._pending and self._depth == 0 and primary:
            parsed = self._resolved(parsed)
            self._pending = False
        return parsed

    def _resolved(self, parsed: _ParsedConfig) -> _ParsedConfig:
        raise NotImplementedError


class _MirrorConfiguration(_FirstConfiguration):
    """Serves the Debian snapshot mirror with the components that the parsed configuration requests."""

    def __init__(self, mirror: release_sandbox.SnapshotMirror, components: Sequence[str], architecture: str) -> None:
        super().__init__()
        self._mirror = mirror
        self._components = components
        self._architecture = architecture

    def _resolved(self, parsed: _ParsedConfig) -> _ParsedConfig:
        validate_architecture(parsed[2], self._architecture)
        _write_mirror_sources(self._mirror, parsed[2], self._components)
        return parsed


class _ConfigurationValidator(_FirstConfiguration):
    """Validates the first configuration that mkosi parses for the requested image, and the INI files it reads.

    A release stage that installs packages also serves the Debian snapshot mirror for the validated configuration.
    """

    def __init__(
        self,
        settings: ReleaseSettings,
        allowed_paths: Sequence[str],
        allowed_extra_tree: Path | None,
        mirror: release_sandbox.SnapshotMirror | None = None,
    ) -> None:
        super().__init__()
        self._original_parse_ini = self._config_module.parse_ini
        self._settings = settings
        self._allowed_paths = allowed_paths
        self._allowed_extra_tree = allowed_extra_tree
        self._declared_roots = tuple(Path(path).resolve() for path in allowed_paths)
        self._mirror = mirror

    def install(self) -> None:
        super().install()
        self._config_module.parse_ini = self.parse_ini

    def _resolved(self, parsed: _ParsedConfig) -> _ParsedConfig:
        images = tuple(_without_proxy_certificates(config) for config in parsed[2])
        images = with_release_ext4_hash_seed(images, self._settings)
        images = with_label_devicetrees(
            images, Path(self._settings.devicetrees) if self._settings.devicetrees else None
        )
        validate_release_configuration(
            tuple(config for config in images if getattr(config, "image", "main") == "main"),
            self._settings,
            self._allowed_paths,
            self._allowed_extra_tree,
        )
        if self._mirror is not None:
            _write_mirror_sources(self._mirror, images, self._settings.components)
        return (parsed[0], parsed[1], images)

    def parse_ini(self, *args: MkosiObject, **kwargs: MkosiObject) -> Iterator[tuple[str, str, str]]:
        path = Path(args[0]).resolve() if args else None
        declared = path is not None and is_declared(path, self._declared_roots)
        for section, setting, value in self._original_parse_ini(*args, **kwargs):
            if self._pending and self._depth == 1 and declared:
                validate_ini_section(section)
            yield section, setting, value


def _without_proxy_certificates(config: MkosiConfig) -> MkosiConfig:
    # mkosi defaults ProxyPeerCertificate= to a host CA bundle; a release build uses no proxy, so it needs none.
    return replace(config, proxy_peer_certificate=None, proxy_client_certificate=None, proxy_client_key=None)


EXT4_MKFS_OPTIONS_VARIABLE = "SYSTEMD_REPART_MKFS_OPTIONS_EXT4"


def derive_ext4_hash_seed(seed: uuid.UUID) -> uuid.UUID:
    """Returns the ext4 directory hash seed of a release, derived from its Seed= like systemd-repart derives UUIDs.

    systemd-repart formats ext4 with a UUID derived from Seed= but lets mkfs.ext4 pick a random directory hash seed.
    Like systemd-repart, this keys an HMAC-SHA256 with the seed and marks the first 16 bytes of the digest as a v4
    UUID.
    """
    digest = hmac.new(seed.bytes, b"ext4-hash-seed", hashlib.sha256).digest()
    return uuid.UUID(bytes=digest[:16], version=4)


def with_derived_ext4_hash_seed(config: MkosiConfig, seed: uuid.UUID) -> MkosiConfig:
    """Returns config with mkfs.ext4 options that pin the ext4 directory hash seed, unless it sets its own options."""
    if EXT4_MKFS_OPTIONS_VARIABLE in config.environment:
        return config
    options = "-E hash_seed={}".format(derive_ext4_hash_seed(seed))
    return replace(config, environment={**config.environment, EXT4_MKFS_OPTIONS_VARIABLE: options})


def with_release_ext4_hash_seed(images: tuple[MkosiConfig, ...], settings: ReleaseSettings) -> tuple[MkosiConfig, ...]:
    """Returns images with a derived ext4 hash seed if the release stage formats partitions.

    A base stage only archives its root, so its configuration stays unchanged.
    """
    if settings.stage == "base":
        return images
    seed = uuid.UUID(settings.seed)
    return tuple(with_derived_ext4_hash_seed(config, seed) for config in images)


def _remove_apt_sources(context: MkosiObject, repositories: Sequence[MkosiObject]) -> None:
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


def _install_sandbox_trees(config: MkosiConfig, dst: Path) -> None:
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


def _install_crypto_policy(config: MkosiConfig, dst: Path) -> None:
    upstream = mkosi_contract.upstream_mkosi()
    policy = config.tools() / "usr/share/crypto-policies/back-ends/DEFAULT"
    if policy.exists():
        (dst / "etc/crypto-policies").mkdir(exist_ok=True)
        upstream.copy_tree(policy, dst / "etc/crypto-policies/back-ends", sandbox=config.sandbox)


def _install_configured_sandbox_trees(config: MkosiConfig, dst: Path) -> None:
    upstream = mkosi_contract.upstream_mkosi()
    if config.sandbox_trees:
        with upstream.complete_step("Copying in sandbox trees…"):
            for sandbox_tree in config.sandbox_trees:
                upstream.install_tree(config, sandbox_tree.source, dst, target=sandbox_tree.target, preserve=False)


def _link_tools_static(config: MkosiConfig, dst: Path) -> None:
    (dst / "etc/static").unlink(missing_ok=True)
    if (config.tools() / "etc/static").is_symlink():
        (dst / "etc/static").symlink_to((config.tools() / "etc/static").readlink())


def deterministic_make_tar(src: Path, dst: Path, *, sandbox: Callable[..., MkosiObject] | None = None) -> None:
    """Archives a root like mkosi v27's make_tar, but with a reproducible member order.

    mkosi's archive follows directory order, which depends on the file system. Sorting by name and not probing for
    holes makes the archive bytes depend only on the tree.
    """
    from mkosi.archive import tar_exclude_apivfs_tmp
    from mkosi.log import complete_step
    from mkosi.run import finalize_passwd_symlinks, nosandbox, run, workdir

    sandbox = sandbox or nosandbox
    root = workdir(src, sandbox)
    with complete_step("Creating reproducible tar archive {}…".format(dst)), dst.open("wb") as archive:
        run(
            tar_command(root, tar_exclude_apivfs_tmp(), os.getuid()),
            stdout=archive,
            sandbox=sandbox(options=["--ro-bind", src, root, *finalize_passwd_symlinks(root)]),
        )


def tar_command(root: str, excludes: Sequence[str], uid: int) -> list[str]:
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
