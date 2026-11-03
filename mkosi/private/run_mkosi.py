#!/usr/bin/python3
"""Run mkosi after resolving Bazel paths before mkosi changes directory."""

import importlib.util
import json
import os
import runpy
import shutil
import subprocess
import sys
import traceback
import uuid
from dataclasses import replace
from pathlib import Path

def _load_diagnostics():
    path = Path(__file__).with_name("diagnostics.py")
    spec = importlib.util.spec_from_file_location("mkosi_diagnostics", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("diagnostic formatter cannot be loaded: {}".format(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

diagnostics = _load_diagnostics()


def _image_version_from_file(path, slot_label_image_id=None):
    """Returns the validated version in path using the sibling image_version.py helper."""
    helper = Path(__file__).with_name("image_version.py")
    spec = importlib.util.spec_from_file_location("rules_mkosi_image_version", helper)
    if spec is None or spec.loader is None:
        raise RuntimeError("image version helper cannot be loaded: {}".format(helper))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        return module.read_image_version(path, slot_label_image_id)
    except (OSError, ValueError) as error:
        raise SystemExit("IMAGE_VERSION_INVALID: {}".format(error)) from None


def _with_image_version(arguments, image_version):
    """Passes image_version to mkosi next to the --image-id= option that it qualifies."""
    image_ids = [index for index, argument in enumerate(arguments) if argument.startswith("--image-id=")]
    if len(image_ids) != 1:
        raise SystemExit("--image-version-file requires exactly one --image-id= mkosi argument")
    return arguments[: image_ids[0] + 1] + ["--image-version=" + image_version] + arguments[image_ids[0] + 1 :]


def _preamble_value(argv, option):
    """Returns the value of a run_mkosi.py preamble option, or None."""
    for index, argument in enumerate(argv[:-1]):
        if argument == "--":
            break
        if argument == option:
            return argv[index + 1]
    return None


def _mkosi_option_value(argv, option):
    """Returns the value of a separate-argument mkosi option after the preamble."""
    arguments = argv[argv.index("--") + 1 :]
    indices = [index for index, argument in enumerate(arguments[:-1]) if argument == option]
    if len(indices) != 1:
        raise SystemExit("expected exactly one mkosi {} argument".format(option))
    return arguments[indices[0] + 1]


def _release_stage(release, debian_snapshot_repository, base_tree, initrd, base_initrd_output):
    """Returns image, base, finalize, or None for a tracer build, and rejects inconsistent options."""
    if base_tree is not None or initrd is not None:
        if base_tree is None or initrd is None:
            raise SystemExit("release finalization requires both --release-base-tree and --release-initrd")
        if debian_snapshot_repository is not None or base_initrd_output is not None:
            raise SystemExit("release finalization cannot use the Debian snapshot or produce a base")
        stage = "finalize"
    elif debian_snapshot_repository is not None:
        stage = "base" if base_initrd_output is not None else "image"
    elif base_initrd_output is not None:
        raise SystemExit("a release base requires the Debian snapshot repository")
    else:
        stage = None
    if (stage is not None) != release:
        raise SystemExit("incomplete release configuration")
    return stage


def _publish_base_initrd(output_directory, destination):
    """Moves mkosi's default initrd, which it names through a relative symlink, to the declared output."""
    link = Path(output_directory) / "initrd"
    if not link.is_symlink():
        raise SystemExit("mkosi did not produce the default initrd link {}".format(link))
    source = link.resolve(strict=True)
    if source.parent != Path(output_directory).resolve() or not source.is_file():
        raise SystemExit("mkosi default initrd {} is not a file in the output directory".format(source))
    link.unlink()
    os.replace(source, destination)

_EPOCH = (0, 0)
_RELEASE_PASSWD = "root:x:0:0:root:/root:/bin/sh\n"
_RELEASE_GROUP = "root:x:0:\n"
_RELEASE_HOSTS = "127.0.0.1 localhost\n::1 localhost\n"
_RELEASE_NSSWITCH = """\
passwd:     files
shadow:     files
group:      files
hosts:      files
services:   files
netgroup:   files
automount:  files

aliases:    files
ethers:     files
gshadow:    files
networks:   files
protocols:  files
publickey:  files
rpc:        files
"""
sys.dont_write_bytecode = True


_PATH_OPTIONS = {
    "-I",
    "--include",
    "-C",
    "--directory",
    "--tools-tree",
    "--extra-search-path",
    "--output-directory",
    "--workspace-directory",
    "--cache-directory",
    "--package-cache-directory",
    "--build-directory",
    "--sandbox-tree",
    "--repart-directory",
    "--base-tree",
    "--initrd",
}

# mkosi constants accepted in place of a path; they are not resolved against the working directory.
_PATH_CONSTANTS = {"--initrd": ("default",)}


def _absolute_paths(arguments):
    result = []
    resolve_next = None
    for argument in arguments:
        if resolve_next:
            if argument in _PATH_CONSTANTS.get(resolve_next, ()):
                result.append(argument)
            else:
                result.append(os.path.abspath(argument))
            resolve_next = None
        elif argument in _PATH_OPTIONS:
            result.append(argument)
            resolve_next = argument
        elif any(argument.startswith(option + "=") for option in _PATH_OPTIONS):
            option, value = argument.split("=", 1)
            if value in _PATH_CONSTANTS.get(option, ()):
                result.append(argument)
            else:
                result.append(option + "=" + os.path.abspath(value))
        else:
            result.append(argument)
    if resolve_next:
        raise SystemExit("mkosi path option is missing its value")
    return result


def _materialize_tree(source, destination, executable_paths=()):
    source = Path(source)
    source_root = source.resolve(strict=True)
    executable_paths = set(executable_paths)
    destination = Path(destination)
    if destination.is_symlink():
        raise SystemExit("materialization destination is a symlink")
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=False)
    os.chmod(destination, 0o755)
    os.utime(destination, _EPOCH)

    def copy_tree(source_dir, target_dir, relative_prefix):
        target_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(target_dir, 0o755)
        os.utime(target_dir, _EPOCH)
        for item in sorted(os.scandir(source_dir), key=lambda entry: entry.name):
            source_path = Path(item.path)
            target_path = target_dir / item.name
            if item.is_symlink():
                resolved = source_path.resolve(strict=True)
                if resolved.is_relative_to(source_root):
                    target_path.symlink_to(os.readlink(source_path))
                    os.utime(target_path, _EPOCH, follow_symlinks=False)
                elif resolved.is_dir():
                    copy_tree(resolved, target_path, relative_prefix / item.name)
                elif resolved.is_file():
                    shutil.copyfile(resolved, target_path)
                    os.chmod(
                        target_path,
                        0o755
                        if (relative_prefix / item.name).as_posix() in executable_paths
                        else 0o644,
                    )
                    os.utime(target_path, _EPOCH)
                else:
                    raise SystemExit("unsupported Bazel input indirection: {}".format(source_path))
            elif item.is_dir(follow_symlinks=False):
                copy_tree(source_path, target_path, relative_prefix / item.name)
            elif item.is_file(follow_symlinks=False):
                shutil.copyfile(source_path, target_path)
                os.chmod(
                    target_path,
                    0o755
                    if (relative_prefix / item.name).as_posix() in executable_paths
                    else 0o644,
                )
                os.utime(target_path, _EPOCH)
            else:
                raise SystemExit("unsupported staged entry: {}".format(source_path))
        os.chmod(target_dir, 0o755)
        os.utime(target_dir, _EPOCH)

    copy_tree(source_root, destination, Path())


def _restore_manifest_links(destination, manifest_path, path_prefix=""):
    entries = json.loads(Path(manifest_path).read_text())
    for entry in entries:
        if entry["kind"] != "symlink":
            continue
        entry_path = entry["path"]
        if path_prefix:
            prefix = path_prefix.rstrip("/") + "/"
            if not entry_path.startswith(prefix):
                continue
            entry_path = entry_path[len(prefix) :]
        relative = Path(entry_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise SystemExit("invalid staging manifest path")
        target = destination / relative
        if target.is_symlink() or target.is_file():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
        else:
            raise SystemExit("staging manifest entry is missing")
        link_target = entry["link_target"]
        if not link_target or os.path.isabs(link_target):
            raise SystemExit("invalid staging manifest link")
        target.symlink_to(link_target)
        os.utime(target, _EPOCH, follow_symlinks=False)
    directories = []
    for root, dirnames, _ in os.walk(destination, followlinks=False):
        directories.append(Path(root))
        for name in dirnames:
            path = Path(root) / name
            if not path.is_symlink():
                directories.append(path)
    for path in sorted(set(directories), reverse=True):
        os.chmod(path, 0o755)
        os.utime(path, _EPOCH)


def _extract_debian_tools(archive, extractor_path, expected_digest, destination):
    if destination.is_symlink():
        raise SystemExit("Debian tools destination is a symlink")
    if destination.exists():
        shutil.rmtree(destination)
    extractor_spec = importlib.util.spec_from_file_location(
        "mkosi_debian_extract_tree",
        extractor_path,
    )
    if extractor_spec is None or extractor_spec.loader is None:
        raise SystemExit("Debian tools extractor cannot be loaded")
    extractor = importlib.util.module_from_spec(extractor_spec)
    extractor_spec.loader.exec_module(extractor)
    extractor.extract(archive, destination, expected_digest)

def _run_mkosi(script, arguments, runner=subprocess.run, environment=None):
    """Run mkosi and classify process-boundary failures without masking exit status."""
    try:
        kwargs = {
            "check": False,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
        }
        if environment is not None:
            kwargs["env"] = environment
        completed = runner([sys.executable, script] + arguments, **kwargs)
    except OSError as error:
        diagnostics.fail("TOOLCHAIN_FAILURE", "mkosi executable cannot start {}: {}".format(script, error))
    if completed.returncode:
        original = completed.stdout + completed.stderr
        tail = original.decode(errors="replace").strip().splitlines()[-8:]
        diagnostics.fail(
            diagnostics.classify_mkosi_output(original),
            "mkosi image assembly exited with status {}: {}".format(
                completed.returncode,
                " | ".join(tail),
            ),
            original,
            exit_code=diagnostics.child_exit_code(completed.returncode),
        )
    for stream, content in ((sys.stdout, completed.stdout), (sys.stderr, completed.stderr)):
        binary_stream = getattr(stream, "buffer", None)
        if binary_stream is None:
            stream.write(content.decode(errors="replace"))
        else:
            binary_stream.write(content)


def _write_release_file(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    os.chmod(path, 0o644)
    os.utime(path, _EPOCH)


def _configure_release_sandbox(workspace, arguments):
    """Supplies fixed sandbox files instead of host /etc state to a release build."""
    sandbox_tree = workspace / "release-sandbox"
    _write_release_file(
        sandbox_tree / "etc/apt/apt.conf.d/99rules-mkosi-release",
        'Acquire::Languages "none";\nAcquire::By-Hash "no";\n',
    )
    _write_release_file(sandbox_tree / "etc/passwd", _RELEASE_PASSWD)
    _write_release_file(sandbox_tree / "etc/group", _RELEASE_GROUP)
    _write_release_file(sandbox_tree / "etc/hosts", _RELEASE_HOSTS)
    _write_release_file(sandbox_tree / "etc/nsswitch.conf", _RELEASE_NSSWITCH)
    arguments.extend(["--sandbox-tree", os.fspath(sandbox_tree)])


def _configure_release_mirror(source, workspace, arguments):
    mirror = workspace / "debian-snapshot"
    _materialize_tree(source, mirror)
    arguments.extend(["--local-mirror", "file://" + os.fspath(mirror)])
    _configure_release_sandbox(workspace, arguments)
    return mirror


def _configuration_paths(value):
    if isinstance(value, Path):
        yield value
    elif hasattr(value, "source"):
        source = value.source
        if source:
            yield from _configuration_paths(source)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _configuration_paths(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _configuration_paths(item)


def _release_apt_components(repositories, release_components):
    """Return mkosi's Debian components for the release mirror, or fail closed."""
    components = tuple(dict.fromkeys(("main", *repositories)))
    missing = [component for component in components if component not in release_components]
    if missing:
        raise SystemExit(
            "release configuration Repositories= requests components absent from the "
            "Debian snapshot: {} (snapshot components: {})".format(
                ", ".join(missing),
                ", ".join(release_components),
            )
        )
    return components


def _validate_release_ini_entry(section):
    if section in ("Match", "TriggerMatch"):
        raise SystemExit(
            "release configuration cannot use [{}] host-dependent matching".format(
                section
            )
        )


def _validate_release_stage(config, release_stage, base_tree, base_initrd):
    """Checks the settings that separate a cacheable base from its versioned finalization."""
    if release_stage == "base":
        if getattr(config, "image_version", None):
            raise SystemExit(
                "release base configuration cannot set ImageVersion=; set the version on the "
                "mkosi_image that finalizes the base"
            )
    elif release_stage == "finalize":
        for name, setting in (
            ("packages", "Packages="),
            ("build_packages", "BuildPackages="),
            ("volatile_packages", "VolatilePackages="),
            ("remove_packages", "RemovePackages="),
            ("package_directories", "PackageDirectories="),
            ("volatile_package_directories", "VolatilePackageDirectories="),
        ):
            if getattr(config, name, ()):
                raise SystemExit(
                    "release finalize configuration cannot use {}: packages are installed only by "
                    "mkosi_base, which has the Debian snapshot".format(setting)
                )
        base_trees = [Path(path).resolve() for path in getattr(config, "base_trees", ())]
        if base_trees != [base_tree]:
            raise SystemExit(
                "release finalize configuration BaseTrees= must resolve to exactly the declared base tree"
            )
        initrds = [Path(path).resolve() for path in getattr(config, "initrds", ())]
        if initrds != [base_initrd]:
            raise SystemExit(
                "release finalize configuration Initrds= must resolve to exactly the declared base initrd"
            )
        cacheonly = getattr(getattr(config, "cacheonly", None), "value", "always")
        if cacheonly != "always":
            raise SystemExit(
                "release finalize configuration CacheOnly= must resolve to always so that no package "
                "metadata is synchronized"
            )
    elif release_stage != "image":
        raise SystemExit("unknown release stage {}".format(release_stage))


def _validate_release_configuration(
    images,
    release_seed,
    release_source_date_epoch,
    release_distribution,
    release_codename,
    release_snapshot,
    allowed_paths,
    allowed_extra_tree=None,
    release_firmware="uefi",
    release_components=("main",),
    release_stage="image",
    base_tree=None,
    base_initrd=None,
):
    expected_seed = uuid.UUID(release_seed)
    if release_stage == "finalize":
        if base_tree is None or base_initrd is None:
            raise SystemExit("release finalization requires a declared base tree and initrd")
        base_tree = Path(base_tree).resolve()
        base_initrd = Path(base_initrd).resolve()
        # The declared base artifacts are action inputs, so finalization may read them like the staged configuration.
        allowed_paths = (*allowed_paths, base_tree, base_initrd)
    allowed_roots = [Path(path).resolve() for path in allowed_paths]
    images = tuple(images)
    for index, config in enumerate(images):
        # mkosi appends the requested image after generated dependency images
        # such as mkosi-initrd. Firmware selection constrains that primary
        # image. Generated dependency defaults are pinned mkosi resources, not
        # caller configuration, and may intentionally use distinct seeds.
        if index != len(images) - 1:
            continue
        if release_firmware == "bios":
            if getattr(config, "secure_boot", False):
                raise SystemExit("bios firmware is incompatible with SecureBoot")
            if getattr(getattr(config, "unified_kernel_images", None), "value", "no") == "yes":
                raise SystemExit("bios firmware is incompatible with UnifiedKernelImages")
            bootloader = getattr(config, "bootloader", None)
            bootloader_name = getattr(bootloader, "name", str(bootloader or "none")).lower()
            if bootloader_name != "none":
                raise SystemExit("bios firmware is incompatible with a UEFI Bootloader")
        if getattr(config, "proxy_url", None):
            raise SystemExit("release configuration cannot use a proxy")
        if getattr(getattr(config, "incremental", None), "value", "no") != "no":
            raise SystemExit("release configuration incremental mode is not supported")
        if getattr(config, "distribution", None) and (
            config.distribution.value != release_distribution or
            config.release != release_codename or
            (
                config.snapshot != release_snapshot
                # Finalization installs no packages, so it may leave the snapshot unset.
                and not (release_stage == "finalize" and config.snapshot is None)
            )
        ):
            raise SystemExit(
                "release configuration must resolve to {} {} snapshot {}".format(
                    release_distribution,
                    release_codename,
                    release_snapshot,
                )
            )
        _release_apt_components(getattr(config, "repositories", ()), release_components)
        _validate_release_stage(config, release_stage, base_tree, base_initrd)
        if config.seed != expected_seed:
            raise SystemExit(
                "release configuration Seed must resolve to {}".format(expected_seed)
            )
        if config.source_date_epoch != release_source_date_epoch:
            raise SystemExit(
                "release configuration SourceDateEpoch must resolve to {}".format(
                    release_source_date_epoch
                )
            )
        extra_trees = getattr(config, "extra_trees", ())
        if extra_trees and (
            allowed_extra_tree is None
            or any(
                Path(tree.source).resolve() != allowed_extra_tree
                for tree in extra_trees
            )
        ):
            raise SystemExit("release configuration extra_trees is not supported")
        for name in (
            "kernel_modules_include",
            "kernel_modules_initrd_include",
        ):
            if "host" in getattr(config, name, ()):
                raise SystemExit(
                    "release configuration {} cannot include host modules".format(name)
                )
        for name, value in vars(config).items():
            for path in _configuration_paths(value):
                resolved = path.resolve()
                if not any(
                    resolved == root or resolved.is_relative_to(root)
                    for root in allowed_roots
                ):
                    raise SystemExit(
                        "release configuration {} resolves undeclared path {}".format(
                            name,
                            resolved,
                        )
                    )
        for name in (
            "sync_scripts",
            "prepare_scripts",
            "build_scripts",
            "postinst_scripts",
            "finalize_scripts",
            "postoutput_scripts",
            "configure_scripts",
            "clean_scripts",
            "microcode_host",
            "kernel_modules_include_host",
            "kernel_modules_initrd_include_host",
        ):
            if getattr(config, name, ()):
                raise SystemExit(
                    "release configuration {} is not supported".format(name)
                )
        for name in (
            "secure_boot_key_source",
            "secure_boot_certificate_source",
            "verity_key_source",
            "verity_certificate_source",
            "sign_expected_pcr_key_source",
            "sign_expected_pcr_certificate_source",
        ):
            if getattr(getattr(config, name, None), "source", None):
                raise SystemExit(
                    "release configuration {} is not supported".format(name)
                )
    return tuple(allowed_roots)


def _activate_release_mode(
    mirror,
    release_seed,
    release_source_date_epoch,
    release_distribution,
    release_codename,
    release_snapshot,
    allowed_paths,
    allowed_extra_tree,
    release_firmware,
    release_components,
    release_stage="image",
    base_tree=None,
    base_initrd=None,
):
    """Mount a long Bazel path at mkosi's stable in-sandbox repository path.

    mkosi v27 registers a local mirror with only the main component. The
    snapshot can stage more components, so the mirror source instead lists
    main plus the components requested through Repositories=, each of which
    must be present in the snapshot.

    A finalize stage has no mirror: it installs no packages and reads only the
    declared base tree and initrd. A base stage archives its root with
    _deterministic_make_tar so that the archive can cross Bazel's cache.
    """
    from pathlib import Path

    import mkosi
    import mkosi.config
    import mkosi.distribution.debian
    from mkosi.context import Context
    from mkosi.distribution.debian import Installer
    from mkosi.installer import PackageManager

    if (mirror is None) != (release_stage == "finalize"):
        raise SystemExit("only the release finalize stage runs without the Debian snapshot mirror")
    mirror = os.fspath(mirror) if mirror is not None else None
    source_url = "file://" + mirror if mirror is not None else None
    original_context_init = Context.__init__
    original_mounts = PackageManager.mounts.__func__
    original_repositories = Installer.repositories.__func__
    original_parse_config = mkosi.config.parse_config
    original_parse_ini = mkosi.config.parse_ini
    validate_initial_configuration = [True]
    declared_roots = tuple(Path(path).resolve() for path in allowed_paths)
    parse_depth = [0]

    def repositories(cls, context, for_image=False):
        if for_image:
            return
        for repository in original_repositories(cls, context, for_image):
            if repository.url == source_url:
                yield replace(
                    repository,
                    url="file:///repository",
                    components=_release_apt_components(
                        context.config.repositories,
                        release_components,
                    ),
                )
            else:
                yield repository

    def mounts(cls, context):
        result = original_mounts(cls, context)
        for index in range(len(result) - 2):
            if (
                result[index] == "--bind"
                and os.fspath(result[index + 1]) == mirror
                and result[index + 2] == "/repository"
            ):
                result[index] = "--ro-bind"
                break
        else:
            raise SystemExit("mkosi did not register the declared release mirror")
        for index in range(len(result) - 2):
            if (
                result[index] == "--ro-bind"
                and os.fspath(result[index + 1]) == mirror
                and os.fspath(result[index + 2]) == mirror
            ):
                del result[index : index + 3]
                break
        return result

    def context_init(self, *args, **kwargs):
        original_context_init(self, *args, **kwargs)
        self._rules_mkosi_release_mirror = True

    def repository(self):
        if not getattr(self, "_rules_mkosi_release_mirror", False):
            return self.workspace / "repository"
        return Path(mirror)

    def parse_config(*args, **kwargs):
        primary_configuration = "mkosi-initrd" not in os.fspath(
            kwargs.get("resources", "/")
        )
        parse_depth[0] += 1
        try:
            parsed = original_parse_config(*args, **kwargs)
        finally:
            parse_depth[0] -= 1
        if validate_initial_configuration[0] and parse_depth[0] == 0 and primary_configuration:
            images = tuple(
                replace(
                    config,
                    proxy_peer_certificate = None,
                    proxy_client_certificate = None,
                    proxy_client_key = None,
                )
                for config in parsed[2]
            )
            _validate_release_configuration(
                tuple(
                    config
                    for config in images
                    if getattr(config, "image", "main") == "main"
                ),
                release_seed,
                release_source_date_epoch,
                release_distribution,
                release_codename,
                release_snapshot,
                allowed_paths,
                allowed_extra_tree,
                release_firmware,
                release_components,
                release_stage,
                base_tree,
                base_initrd,
            )
            validate_initial_configuration[0] = False
            return (parsed[0], parsed[1], images)
        return parsed

    def parse_ini(*args, **kwargs):
        path = Path(args[0]).resolve() if args else None
        declared = path is not None and any(
            path == root or root in path.parents
            for root in declared_roots
        )
        for section, setting, value in original_parse_ini(*args, **kwargs):
            if validate_initial_configuration[0] and parse_depth[0] == 1 and declared:
                _validate_release_ini_entry(section)
            yield section, setting, value

    def install_sandbox_trees(config, dst):
        (dst / "etc").mkdir(exist_ok=True)

        if (policy := config.tools() / "usr/share/crypto-policies/back-ends/DEFAULT").exists():
            Path(dst / "etc/crypto-policies").mkdir(exist_ok=True)
            mkosi.copy_tree(policy, dst / "etc/crypto-policies/back-ends", sandbox=config.sandbox)

        if config.sandbox_trees:
            with mkosi.complete_step("Copying in sandbox trees…"):
                for tree in config.sandbox_trees:
                    mkosi.install_tree(config, tree.source, dst, target=tree.target, preserve=False)

        if not (dst / "etc/mtab").is_symlink():
            (dst / "etc/mtab").symlink_to("../proc/self/mounts")

        Path(dst / "etc/resolv.conf").unlink(missing_ok=True)
        Path(dst / "etc/resolv.conf").touch()

        if not (dst / "etc/nsswitch.conf").exists():
            _write_release_file(dst / "etc/nsswitch.conf", _RELEASE_NSSWITCH)

        Path(dst / "etc/static").unlink(missing_ok=True)
        if (config.tools() / "etc/static").is_symlink():
            (dst / "etc/static").symlink_to((config.tools() / "etc/static").readlink())

        for directory in (
            "etc/pki/ca-trust",
            "etc/pki/tls",
            "etc/ssl",
            "etc/ca-certificates",
            "etc/pacman.d/gnupg",
            "etc/alternatives",
        ):
            (dst / directory).mkdir(parents=True, exist_ok=True)
        for filename in ("etc/shadow", "etc/gshadow", "etc/ld.so.cache"):
            (dst / filename).touch(exist_ok=True)

    def install_apt_sources(context, repositories):
        del repositories
        apt = context.root / "etc/apt"
        (apt / "sources.list").unlink(missing_ok=True)
        sources = apt / "sources.list.d"
        if sources.exists():
            for source in sources.iterdir():
                if source.is_file() and source.suffix in (".list", ".sources"):
                    source.unlink()

    Context.__init__ = context_init
    if mirror is not None:
        Installer.repositories = classmethod(repositories)
        PackageManager.mounts = classmethod(mounts)
        Context.repository = property(repository)
    mkosi.config.parse_config = parse_config
    mkosi.config.parse_ini = parse_ini
    mkosi.distribution.debian.install_apt_sources = install_apt_sources
    mkosi.install_sandbox_trees = install_sandbox_trees
    if release_stage == "base":
        mkosi.make_tar = _deterministic_make_tar


def _deterministic_make_tar(src, dst, *, sandbox=None):
    """Archives a root like mkosi v27's make_tar, but with a reproducible member order.

    mkosi's archive follows directory order, which depends on the file system. Sorting
    by name and not probing for holes makes the archive bytes depend only on the tree.
    """
    from mkosi.archive import tar_exclude_apivfs_tmp
    from mkosi.log import complete_step
    from mkosi.run import finalize_passwd_symlinks, nosandbox, run, workdir

    sandbox = sandbox or nosandbox
    with complete_step("Creating reproducible tar archive {}…".format(dst)):
        with dst.open("wb") as f:
            run(
                [
                    "tar",
                    "--create",
                    "--file",
                    "-",
                    "--directory",
                    workdir(src, sandbox),
                    "--sort=name",
                    "--acls",
                    "--selinux",
                    "--xattrs",
                    "--pax-option=delete=atime,delete=ctime,delete=mtime",
                    "--force-local",
                    *(["--owner=root:0"] if os.getuid() != 0 else []),
                    *(["--group=root:0"] if os.getuid() != 0 else []),
                    *tar_exclude_apivfs_tmp(),
                    ".",
                ],
                stdout=f,
                sandbox=sandbox(
                    options=[
                        "--ro-bind",
                        src,
                        workdir(src, sandbox),
                        *finalize_passwd_symlinks(workdir(src, sandbox)),
                    ],
                ),
            )


def main():
    if len(sys.argv) < 3:
        raise SystemExit("usage: run_mkosi.py MKOSI_SCRIPT [--executable-path PATH] -- [mkosi arguments]")
    release_child = os.environ.get("RULES_MKOSI_RELEASE_CHILD") == "1"
    release_parent = any(
        option in sys.argv[2:] for option in ("--debian-snapshot-repository", "--release-base-tree")
    )
    if release_parent and not release_child:
        # Reject an invalid version before the release child starts, so that the failure is not reported as an
        # mkosi assembly failure.
        image_version_file = _preamble_value(sys.argv[2:], "--image-version-file")
        if image_version_file is not None:
            _image_version_from_file(image_version_file, _preamble_value(sys.argv[2:], "--slot-label-image-id"))
        environment = dict(os.environ)
        environment["RULES_MKOSI_RELEASE_CHILD"] = "1"
        _run_mkosi(
            os.path.abspath(__file__),
            sys.argv[1:],
            environment=environment,
        )
        base_initrd_output = _preamble_value(sys.argv[2:], "--release-base-initrd-output")
        if base_initrd_output is not None:
            _publish_base_initrd(_mkosi_option_value(sys.argv[2:], "--output-directory"), base_initrd_output)
        return
    script = os.path.abspath(sys.argv[1])
    preamble_end = 2
    executable_paths = []
    staging_manifest = None
    debian_tools_archive = None
    debian_tools_extractor = None
    debian_tools_sha256 = None
    kernel_preflight = None
    debian_snapshot_repository = None
    release_mirror = None
    release_seed = None
    release_source_date_epoch = None
    release_distribution = None
    release_codename = None
    release_snapshot = None
    release_firmware = None
    release_components = None
    image_version_file = None
    slot_label_image_id = None
    release_base_tree = None
    release_initrd = None
    release_base_initrd_output = None
    while preamble_end < len(sys.argv) and sys.argv[preamble_end] != "--":
        option = sys.argv[preamble_end]
        if option == "--executable-path" and preamble_end + 1 < len(sys.argv):
            executable_paths.append(sys.argv[preamble_end + 1])
            preamble_end += 2
        elif option == "--staging-manifest" and preamble_end + 1 < len(sys.argv):
            staging_manifest = os.path.abspath(sys.argv[preamble_end + 1])
            preamble_end += 2
        elif option == "--debian-tools-archive" and preamble_end + 1 < len(sys.argv):
            debian_tools_archive = os.path.abspath(sys.argv[preamble_end + 1])
            preamble_end += 2
        elif option == "--debian-tools-extractor" and preamble_end + 1 < len(sys.argv):
            debian_tools_extractor = os.path.abspath(sys.argv[preamble_end + 1])
            preamble_end += 2
        elif option == "--debian-tools-sha256" and preamble_end + 1 < len(sys.argv):
            debian_tools_sha256 = sys.argv[preamble_end + 1]
            preamble_end += 2
        elif option == "--kernel-preflight" and preamble_end + 1 < len(sys.argv):
            kernel_preflight = os.path.abspath(sys.argv[preamble_end + 1])
            preamble_end += 2
        elif option == "--debian-snapshot-repository" and preamble_end + 1 < len(sys.argv):
            debian_snapshot_repository = os.path.abspath(sys.argv[preamble_end + 1])
            preamble_end += 2
        elif option == "--release-seed" and preamble_end + 1 < len(sys.argv):
            release_seed = sys.argv[preamble_end + 1]
            preamble_end += 2
        elif option == "--release-source-date-epoch" and preamble_end + 1 < len(sys.argv):
            try:
                release_source_date_epoch = int(sys.argv[preamble_end + 1])
            except ValueError as error:
                raise SystemExit("release source date epoch must be an integer") from error
            preamble_end += 2
        elif option == "--release-distribution" and preamble_end + 1 < len(sys.argv):
            release_distribution = sys.argv[preamble_end + 1]
            preamble_end += 2
        elif option == "--release-codename" and preamble_end + 1 < len(sys.argv):
            release_codename = sys.argv[preamble_end + 1]
            preamble_end += 2
        elif option == "--release-snapshot" and preamble_end + 1 < len(sys.argv):
            release_snapshot = sys.argv[preamble_end + 1]
            preamble_end += 2
        elif option == "--release-firmware" and preamble_end + 1 < len(sys.argv):
            release_firmware = sys.argv[preamble_end + 1]
            preamble_end += 2
        elif option == "--image-version-file" and preamble_end + 1 < len(sys.argv):
            image_version_file = os.path.abspath(sys.argv[preamble_end + 1])
            preamble_end += 2
        elif option == "--slot-label-image-id" and preamble_end + 1 < len(sys.argv):
            slot_label_image_id = sys.argv[preamble_end + 1]
            preamble_end += 2
        elif option == "--release-base-tree" and preamble_end + 1 < len(sys.argv):
            release_base_tree = os.path.abspath(sys.argv[preamble_end + 1])
            preamble_end += 2
        elif option == "--release-initrd" and preamble_end + 1 < len(sys.argv):
            release_initrd = os.path.abspath(sys.argv[preamble_end + 1])
            preamble_end += 2
        elif option == "--release-base-initrd-output" and preamble_end + 1 < len(sys.argv):
            release_base_initrd_output = os.path.abspath(sys.argv[preamble_end + 1])
            preamble_end += 2
        elif option == "--release-components" and preamble_end + 1 < len(sys.argv):
            release_components = tuple(sys.argv[preamble_end + 1].split(","))
            if "main" not in release_components or "" in release_components:
                raise SystemExit("release components must be a comma-separated list including main")
            preamble_end += 2
        else:
            raise SystemExit("invalid run_mkosi.py preamble")
    if preamble_end == len(sys.argv):
        raise SystemExit("run_mkosi.py preamble is missing --")
    if not kernel_preflight:
        raise SystemExit("run_mkosi.py requires --kernel-preflight")
    if os.environ.get("PYTHONPATH"):
        python_paths = os.environ["PYTHONPATH"].split(os.pathsep)
        os.environ["PYTHONPATH"] = os.pathsep.join(
            os.path.abspath(path or ".")
            for path in python_paths
        )
        sys.path[:] = [
            os.path.abspath(path) if path in python_paths else path
            for path in sys.path
        ]
    arguments = _absolute_paths(sys.argv[preamble_end + 1 :])
    if image_version_file is not None:
        arguments = _with_image_version(
            arguments,
            _image_version_from_file(image_version_file, slot_label_image_id),
        )
    diagnostics.run_kernel_preflight(kernel_preflight, "mkosi image assembly")
    debian_options = (
        debian_tools_archive,
        debian_tools_extractor,
        debian_tools_sha256,
    )
    if any(debian_options) and not all(debian_options):
        raise SystemExit("incomplete Debian tools archive configuration")
    release_options = (
        release_seed,
        release_source_date_epoch,
        release_distribution,
        release_codename,
        release_snapshot,
        release_firmware,
        release_components,
    )
    if any(option is not None for option in release_options) and not all(
        option is not None for option in release_options
    ):
        raise SystemExit("incomplete release configuration")
    release_stage = _release_stage(
        any(option is not None for option in release_options),
        debian_snapshot_repository,
        release_base_tree,
        release_initrd,
        release_base_initrd_output,
    )
    if all(debian_options):
        workspace = Path(arguments[arguments.index("--workspace-directory") + 1])
        tools_root = Path(arguments[arguments.index("--tools-tree") + 1])
        expected_tools_root = workspace / "debian-tools"
        if tools_root != expected_tools_root:
            raise SystemExit("Debian tools destination must be inside the mkosi workspace")
        workspace.mkdir(parents=True, exist_ok=True)
        _extract_debian_tools(
            debian_tools_archive,
            debian_tools_extractor,
            debian_tools_sha256,
            tools_root,
        )
    if debian_snapshot_repository:
        workspace = Path(arguments[arguments.index("--workspace-directory") + 1])
        release_mirror = _configure_release_mirror(debian_snapshot_repository, workspace, arguments)
    elif release_stage == "finalize":
        workspace = Path(arguments[arguments.index("--workspace-directory") + 1])
        _configure_release_sandbox(workspace, arguments)
    if "-C" in arguments:
        directory = Path(arguments[arguments.index("-C") + 1])
        workspace = Path(arguments[arguments.index("--workspace-directory") + 1])
        materialized = workspace / "staging-root"
        _materialize_tree(directory, materialized, executable_paths)
        if staging_manifest:
            _restore_manifest_links(materialized, staging_manifest)
        arguments[arguments.index("-C") + 1] = os.fspath(materialized)
        for option in ("-I", "--include"):
            for index, argument in enumerate(arguments):
                if argument.startswith(os.fspath(directory) + os.sep):
                    arguments[index] = os.fspath(materialized) + argument[len(os.fspath(directory)) :]
    if release_stage is not None:
        allowed_paths = []
        for index, argument in enumerate(arguments):
            if argument in _PATH_OPTIONS and index + 1 < len(arguments):
                if arguments[index + 1] not in _PATH_CONSTANTS.get(argument, ()):
                    allowed_paths.append(arguments[index + 1])
        _activate_release_mode(
            os.fspath(release_mirror) if release_mirror else None,
            release_seed,
            release_source_date_epoch,
            release_distribution,
            release_codename,
            release_snapshot,
            allowed_paths,
            (materialized / "mkosi.extra").resolve()
            if (materialized / "mkosi.extra").is_dir()
            else None,
            release_firmware,
            release_components,
            release_stage,
            release_base_tree,
            release_initrd,
        )
    if release_child:
        sys.argv[:] = [script] + arguments
        try:
            runpy.run_path(script, run_name="__main__")
        except SystemExit as error:
            if error.code not in (None, 0):
                print(
                    "rules_mkosi release child failed: status={!r}; command={!r}".format(
                        error.code,
                        sys.argv,
                    ),
                    file=sys.stderr,
                )
                traceback.print_exc(file=sys.stderr)
            raise
    else:
        _run_mkosi(script, arguments)


if __name__ == "__main__":
    main()
