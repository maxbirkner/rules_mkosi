"""Rejects release configurations whose image could depend on undeclared inputs or on the build host."""

import uuid
from dataclasses import dataclass
from pathlib import Path

from . import repart_definitions


@dataclass(frozen=True)
class ReleaseSettings:
    """The release contract that the Bazel rule passes to run_mkosi.py."""

    seed: str
    source_date_epoch: int
    distribution: str
    codename: str
    snapshot: str
    firmware: str = "uefi"
    components: tuple[str, ...] = ("main",)
    stage: str = "image"
    base_tree: str | None = None
    base_initrd: str | None = None


@dataclass(frozen=True)
class _Context:
    settings: ReleaseSettings
    seed: uuid.UUID
    base: tuple[Path, Path] | None
    allowed_roots: tuple[Path, ...]
    allowed_extra_tree: Path | None


def validate_release_configuration(images, settings, allowed_paths, allowed_extra_tree=None):
    """Validates the parsed images of a release build and returns the resolved roots that it may read."""
    seed = uuid.UUID(settings.seed)
    base = _declared_base(settings)
    # The declared base artifacts are action inputs, so finalization may read them like the staged configuration.
    allowed_roots = tuple(Path(path).resolve() for path in (*allowed_paths, *(base or ())))
    images = tuple(images)
    # mkosi appends the requested image after generated dependency images such as mkosi-initrd. Generated dependency
    # defaults are pinned mkosi resources, not caller configuration, and may intentionally use distinct seeds.
    if images:
        context = _Context(settings, seed, base, allowed_roots, allowed_extra_tree)
        for check in _PRIMARY_IMAGE_CHECKS:
            check(images[-1], context)
    return allowed_roots


def _declared_base(settings):
    if settings.stage != "finalize":
        return None
    if settings.base_tree is None or settings.base_initrd is None:
        raise SystemExit("release finalization requires a declared base tree and initrd")
    return Path(settings.base_tree).resolve(), Path(settings.base_initrd).resolve()


def is_declared(path, roots):
    return any(path.is_relative_to(root) for root in roots)


def validate_ini_section(section):
    if section in ("Match", "TriggerMatch"):
        raise SystemExit("release configuration cannot use [{}] host-dependent matching".format(section))


def release_apt_components(repositories, release_components):
    """Returns mkosi's Debian components for the release mirror, or fails closed."""
    components = tuple(dict.fromkeys(("main", *repositories)))
    missing = [component for component in components if component not in release_components]
    if missing:
        raise SystemExit(
            "configuration Repositories= requests components absent from the "
            "Debian snapshot: {} (snapshot components: {})".format(", ".join(missing), ", ".join(release_components))
        )
    return components


def validate_finalize_config_directory(directory):
    """Rejects default initrd configuration that a finalization would silently ignore."""
    directory = Path(directory)
    if not (directory / "mkosi.conf").exists() and (directory / "mkosi/mkosi.conf").is_file():
        directory = directory / "mkosi"
    for name in ("mkosi.initrd.conf", "mkosi.initrd"):
        if (directory / name).exists() or (directory / name).is_symlink():
            raise SystemExit(
                "release finalize configuration cannot contain {}: the default initrd is built by "
                "mkosi_base, so put it in the base configuration".format(name)
            )


def _enum_value(config, name, default):
    return getattr(getattr(config, name, None), "value", default)


def _is_set(name):
    return lambda config: bool(getattr(config, name, ()))


def _has_source(name):
    return lambda config: bool(getattr(getattr(config, name, None), "source", None))


def _includes_host(name):
    return lambda config: "host" in getattr(config, name, ())


def _reject_first(config, rules, message):
    """Fails with message, formatted with the label of the first (label, violated) rule that config violates."""
    for label, violated in rules:
        if violated(config):
            raise SystemExit(message.format(label))


def _set_rules(names_and_labels):
    return tuple((label, _is_set(name)) for name, label in names_and_labels)


_BASE_KERNEL_MODULES_INITRD_RULES = (
    ("KernelModulesInitrd=no", lambda config: getattr(config, "kernel_modules_initrd", True) is False),
    ("KernelModulesInitrdInclude=/KernelInitrdModules=", _is_set("kernel_modules_initrd_include")),
    ("KernelModulesInitrdExclude=", _is_set("kernel_modules_initrd_exclude")),
)

_FINALIZE_INITRD_RULES = _set_rules(
    (
        ("initrd_packages", "InitrdPackages="),
        ("initrd_volatile_packages", "InitrdVolatilePackages="),
        ("initrd_profiles", "InitrdProfiles="),
    )
)

_FINALIZE_PACKAGE_RULES = _set_rules(
    (
        ("packages", "Packages="),
        ("build_packages", "BuildPackages="),
        ("volatile_packages", "VolatilePackages="),
        ("remove_packages", "RemovePackages="),
        ("package_directories", "PackageDirectories="),
        ("volatile_package_directories", "VolatilePackageDirectories="),
    )
)

_HOST_MODULE_RULES = tuple(
    (name, _includes_host(name)) for name in ("kernel_modules_include", "kernel_modules_initrd_include")
)

_UNSUPPORTED_RULES = tuple(
    (name, _is_set(name))
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
    )
) + tuple(
    (name, _has_source(name))
    for name in (
        "secure_boot_key_source",
        "secure_boot_certificate_source",
        "verity_key_source",
        "verity_certificate_source",
        "sign_expected_pcr_key_source",
        "sign_expected_pcr_certificate_source",
    )
)


def _check_firmware(config, context):
    if context.settings.firmware != "bios":
        return
    if getattr(config, "secure_boot", False):
        raise SystemExit("bios firmware is incompatible with SecureBoot")
    if _enum_value(config, "unified_kernel_images", "no") == "yes":
        raise SystemExit("bios firmware is incompatible with UnifiedKernelImages")
    bootloader = getattr(config, "bootloader", None)
    if getattr(bootloader, "name", str(bootloader or "none")).lower() != "none":
        raise SystemExit("bios firmware is incompatible with a UEFI Bootloader")


def _check_network_and_cache(config, context):
    if getattr(config, "proxy_url", None):
        raise SystemExit("release configuration cannot use a proxy")
    if _enum_value(config, "incremental", "no") != "no":
        raise SystemExit("release configuration incremental mode is not supported")


def _check_distribution(config, context):
    if not getattr(config, "distribution", None):
        return
    settings = context.settings
    if (
        config.distribution.value != settings.distribution
        or config.release != settings.codename
        or not _snapshot_matches(config, settings)
    ):
        raise SystemExit(
            "release configuration must resolve to {} {} snapshot {}".format(
                settings.distribution, settings.codename, settings.snapshot
            )
        )


def _snapshot_matches(config, settings):
    # Finalization installs no packages, so it may leave the snapshot unset.
    return config.snapshot == settings.snapshot or (settings.stage == "finalize" and config.snapshot is None)


def _check_repositories(config, context):
    release_apt_components(getattr(config, "repositories", ()), context.settings.components)


def _check_stage(config, context):
    stage = context.settings.stage
    if stage not in _STAGE_CHECKS:
        raise SystemExit("unknown release stage {}".format(stage))
    _STAGE_CHECKS[stage](config, context)


def _check_base(config, context):
    if getattr(config, "image_version", None):
        raise SystemExit(
            "release base configuration cannot set ImageVersion=; set the version on the "
            "mkosi_image that finalizes the base"
        )
    # The base is not bootable, so mkosi builds the kernel modules initrd only during finalization.
    _reject_first(
        config,
        _BASE_KERNEL_MODULES_INITRD_RULES,
        "release base configuration cannot use {}: the kernel modules initrd is built when mkosi_image(base = ...) "
        "finalizes the base, so set it in the finalize configuration",
    )


def _check_finalize(config, context):
    _reject_first(
        config,
        _FINALIZE_INITRD_RULES,
        "release finalize configuration cannot use {}: the default initrd is built by mkosi_base, so set its "
        "contents in the base configuration",
    )
    _reject_first(
        config,
        _FINALIZE_PACKAGE_RULES,
        "release finalize configuration cannot use {}: packages are installed only by mkosi_base, which has the "
        "Debian snapshot",
    )
    base_tree, base_initrd = context.base
    _require_exactly(config, "base_trees", base_tree, "BaseTrees= must resolve to exactly the declared base tree")
    _require_exactly(config, "initrds", base_initrd, "Initrds= must resolve to exactly the declared base initrd")
    if _enum_value(config, "cacheonly", "always") != "always":
        raise SystemExit(
            "release finalize configuration CacheOnly= must resolve to always so that no package "
            "metadata is synchronized"
        )


def _require_exactly(config, name, expected, requirement):
    if [Path(path).resolve() for path in getattr(config, name, ())] != [expected]:
        raise SystemExit("release finalize configuration " + requirement)


_STAGE_CHECKS = {
    "image": lambda config, context: None,
    "base": _check_base,
    "finalize": _check_finalize,
}


def _check_reproducibility(config, context):
    if config.seed != context.seed:
        raise SystemExit("release configuration Seed must resolve to {}".format(context.seed))
    if config.source_date_epoch != context.settings.source_date_epoch:
        raise SystemExit(
            "release configuration SourceDateEpoch must resolve to {}".format(context.settings.source_date_epoch)
        )


def _check_extra_trees(config, context):
    extra_trees = getattr(config, "extra_trees", ())
    if extra_trees and (
        context.allowed_extra_tree is None
        or any(Path(tree.source).resolve() != context.allowed_extra_tree for tree in extra_trees)
    ):
        raise SystemExit("release configuration extra_trees is not supported")


def _check_host_modules(config, context):
    _reject_first(config, _HOST_MODULE_RULES, "release configuration {} cannot include host modules")


def _check_declared_paths(config, context):
    for name, value in vars(config).items():
        if name in _IMAGE_PATH_SETTINGS:
            continue
        for path in _configuration_paths(value):
            resolved = path.resolve()
            if not is_declared(resolved, context.allowed_roots):
                raise SystemExit("release configuration {} resolves undeclared path {}".format(name, resolved))


# Settings whose paths name files inside the image, not build inputs.
_IMAGE_PATH_SETTINGS = frozenset({"splash"})


def _configuration_paths(value):
    if isinstance(value, Path):
        yield value
    elif hasattr(value, "source"):
        if value.source:
            yield from _configuration_paths(value.source)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _configuration_paths(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _configuration_paths(item)


def _check_verity_hash_sizes(config, context):
    unsized = repart_definitions.unsized_verity_hash_definitions(getattr(config, "repart_dirs", ()))
    if unsized:
        raise SystemExit(
            "release configuration repart definition {} sets Verity=hash without SizeMinBytes= or Minimize=, so "
            "systemd-repart would give its hash partition only 4 KiB; add SizeMinBytes= with room for the hash tree "
            "(about 1% of the data partition), or Minimize=best to it and to its Verity=data partition".format(
                unsized[0]
            )
        )


def _check_unsupported(config, context):
    _reject_first(config, _UNSUPPORTED_RULES, "release configuration {} is not supported")


_PRIMARY_IMAGE_CHECKS = (
    _check_firmware,
    _check_network_and_cache,
    _check_distribution,
    _check_repositories,
    _check_stage,
    _check_reproducibility,
    _check_extra_trees,
    _check_host_modules,
    _check_declared_paths,
    _check_verity_hash_sizes,
    _check_unsupported,
)
