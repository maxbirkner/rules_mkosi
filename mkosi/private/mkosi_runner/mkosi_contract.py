"""Checks that the mkosi internals that release mode patches are the ones that the patches were written for.

mkosi has no supported options for the release constraints in release_patches.py, so release mode replaces mkosi
functions in-process. Each supported mkosi version pins the source of every patched internal, the callers through
which a patch takes effect, and the helpers and fields that the replacements use. A different mkosi then fails the
release build with a list of the changed internals instead of silently building a different image.
"""

import dataclasses
import dis
import hashlib
import importlib
import inspect
from dataclasses import dataclass

_REVIEW = (
    "Review mkosi/private/mkosi_runner/release_patches.py against this mkosi version, then update its contract in "
    "mkosi/private/mkosi_runner/mkosi_contract.py."
)


@dataclass(frozen=True)
class Patched:
    """An mkosi internal that release mode replaces or wraps.

    Attributes:
        name: "module:qualified.name" of the internal.
        patch: The release_patches.py function that replaces or wraps it.
        sha256: SHA-256 of the internal's source in the reviewed mkosi version.
        callers: "module:qualified.name" of functions that must read the patched name from their module at call
            time, so that the patch takes effect.
    """

    name: str
    patch: str
    sha256: str
    callers: tuple[str, ...] = ()


@dataclass(frozen=True)
class Contract:
    """The mkosi internals that release mode depends on in one mkosi version.

    Attributes:
        patched: The internals that release mode replaces or wraps.
        inherited: ("module:Class", attribute) pairs that must not override a patched base class attribute.
        signatures: Parameters, as "module:qualified.name" to parameter list, of the mkosi helpers that the
            replacements call.
        fields: Dataclass fields, as "module:Class" to field names, that the replacements and validation read.
    """

    patched: tuple[Patched, ...]
    inherited: tuple[tuple[str, str], ...]
    signatures: dict[str, str]
    fields: dict[str, tuple[str, ...]]


CONTRACTS = {
    "27.1": Contract(
        patched=(
            Patched(
                "mkosi.distribution.debian:Installer.repositories",
                "_patch_repositories",
                "ec554a20b6b024b2c9c759ba7fd7e901a80bb9612a091072fb5be48e11959998",
            ),
            Patched(
                "mkosi.installer:PackageManager.mounts",
                "_patch_mounts",
                "6b90b94985733b28e30f66cd839fe92e0e6f28b87ed29bb152e65cc5ce5bf7bd",
            ),
            Patched(
                "mkosi.context:Context.__init__",
                "_patch_context_repository",
                "3a8b4a2472bb5c930e7ab43590effa2b206a6e970fb9e77bc1ec3d80e4c95512",
            ),
            Patched(
                "mkosi.context:Context.repository",
                "_patch_context_repository",
                "5828c766cc7063ff43957c152a97cc05a1cf91ff386bd9bd4af44c2a8120f7bc",
            ),
            Patched(
                "mkosi.config:parse_config",
                "_ConfigurationValidator.parse_config",
                "8f949208698e7047d38a27eb1b07e6560994d7483743522f93411f97c90e0171",
                callers=("mkosi.__main__:main",),
            ),
            Patched(
                "mkosi.config:parse_ini",
                "_ConfigurationValidator.parse_ini",
                "8a0f255f47432ec48b271a7df1b4021bf5e2a1e85270f8525ae1c9abe43c5375",
                callers=(
                    "mkosi.config:ParseContext.match_config",
                    "mkosi.config:ParseContext.parse_config_one",
                    "mkosi.config:make_simple_config_parser",
                ),
            ),
            Patched(
                "mkosi.distribution.debian:install_apt_sources",
                "_remove_apt_sources",
                "f180a8169774fc63a5db16397030ff849244b51f1bfd9d3339727488f5e0253f",
                callers=("mkosi.distribution.debian:Installer.install_packages",),
            ),
            Patched(
                "mkosi:install_sandbox_trees",
                "_install_sandbox_trees",
                "cf203faf5bd9cbb4939115a61590c46521472e41bb2b66f671b8d1177bb2b5e7",
                callers=("mkosi:run_sync_scripts", "mkosi:build_image", "mkosi:sync_repository_metadata"),
            ),
            Patched(
                "mkosi:make_tar",
                "deterministic_make_tar",
                "939b475f25dcea19491ee4925fa93af5c487b0e1a7c0b59fcde5c44764237ab2",
                callers=("mkosi:build_image",),
            ),
            Patched(
                "mkosi.manifest:Manifest.record_deb_packages",
                "include_base_packages_in_manifest",
                "39dadbf7082a59af18a2c3ee67059e5b648414f0bc38a3b9695e81822cbc14ea",
            ),
        ),
        inherited=(("mkosi.installer.apt:Apt", "mounts"),),
        signatures={
            "mkosi:copy_tree": "src, dst, *, preserve=, dereference=, use_subvolumes=, sandbox=",
            "mkosi:complete_step": "text, text2=",
            "mkosi:install_tree": "config, src, dst, *, target=, preserve=",
            "mkosi.archive:tar_exclude_apivfs_tmp": "",
            "mkosi.log:complete_step": "text, text2=",
            "mkosi.run:finalize_passwd_symlinks": "root",
            "mkosi.run:nosandbox": "*, options=",
            "mkosi.run:run": (
                "cmdline, check=, stdin=, stdout=, stderr=, input=, env=, log=, success_exit_status=, setup=, "
                "sandbox=, cwd="
            ),
            "mkosi.run:workdir": "path, sandbox=",
            "mkosi.config:Config.tools": "self",
            "mkosi.config:Config.sandbox": (
                "self, *, network=, devices=, relaxed=, tools=, scripts=, overlay=, options="
            ),
        },
        fields={
            "mkosi.config:Config": (
                "image",
                "repositories",
                "sandbox_trees",
                "proxy_peer_certificate",
                "proxy_client_certificate",
                "proxy_client_key",
            ),
            "mkosi.installer.apt:AptRepository": ("url", "components"),
            "mkosi.manifest:Manifest": ("_init_timestamp",),
        },
    ),
}


def mkosi_version():
    """Returns the version of the importable mkosi."""
    from mkosi.sandbox import __version__

    return __version__


def violations(version=None, contract=None):
    """Returns descriptions of the differences between the importable mkosi and the contract of its version."""
    version = mkosi_version() if version is None else version
    if contract is None:
        if version not in CONTRACTS:
            return [
                "mkosi {} is not supported by release mode; supported mkosi versions: {}".format(
                    version, ", ".join(sorted(CONTRACTS))
                )
            ]
        contract = CONTRACTS[version]
    found = []
    for patched in contract.patched:
        found.extend(_patched_violations(patched))
    for owner, attribute in contract.inherited:
        found.extend(_inherited_violations(owner, attribute))
    for name, expected in contract.signatures.items():
        found.extend(_signature_violations(name, expected))
    for owner, names in contract.fields.items():
        found.extend(_field_violations(owner, names))
    return found


def verify():
    """Fails the release build loudly if the importable mkosi differs from the contract of its version."""
    found = violations()
    if found:
        raise SystemExit(
            "mkosi {} internals that rules_mkosi release mode patches differ from the reviewed ones:\n{}\n{}".format(
                mkosi_version(), "\n".join("  - " + violation for violation in found), _REVIEW
            )
        )


def resolve(name):
    """Returns the object named "module:qualified.name", without binding class attributes, or raises LookupError."""
    module_name, _, qualified = name.partition(":")
    try:
        value = importlib.import_module(module_name)
    except ImportError as error:
        raise LookupError(name) from error
    for part in qualified.split("."):
        namespace = vars(value) if isinstance(value, type) else None
        if namespace is not None and part in namespace:
            value = namespace[part]
        elif hasattr(value, part):
            value = getattr(value, part)
        else:
            raise LookupError(name)
    return value


def source_sha256(value):
    """Returns the SHA-256 of the source of a function, method, classmethod, or property."""
    return hashlib.sha256(inspect.getsource(_function(value)).encode()).hexdigest()


def parameters(value):
    """Returns the parameter names and kinds of a callable, without annotations or default values."""
    signature = inspect.signature(inspect.unwrap(_function(value)))
    described = []
    keyword_only = False
    for parameter in signature.parameters.values():
        if parameter.kind is parameter.KEYWORD_ONLY and not keyword_only:
            described.append("*")
            keyword_only = True
        prefix = {parameter.VAR_POSITIONAL: "*", parameter.VAR_KEYWORD: "**"}.get(parameter.kind, "")
        default = "=" if parameter.default is not parameter.empty else ""
        keyword_only = keyword_only or parameter.kind is parameter.VAR_POSITIONAL
        described.append(prefix + parameter.name + default)
    return ", ".join(described)


def _function(value):
    if isinstance(value, (classmethod, staticmethod)):
        return value.__func__
    if isinstance(value, property):
        return value.fget
    return value


def _patched_violations(patched):
    try:
        value = resolve(patched.name)
    except LookupError:
        return ["{} no longer exists; {} cannot patch it".format(patched.name, patched.patch)]
    found = []
    if source_sha256(value) != patched.sha256:
        found.append("{} changed; {} replaces or wraps it".format(patched.name, patched.patch))
    attribute = patched.name.rpartition(".")[2].rpartition(":")[2]
    for caller in patched.callers:
        found.extend(_caller_violations(caller, attribute, patched))
    return found


def _caller_violations(caller, attribute, patched):
    try:
        function = inspect.unwrap(_function(resolve(caller)))
    except LookupError:
        return ["{} no longer exists; {} relies on it to call {}".format(caller, patched.patch, patched.name)]
    if attribute not in _global_names(function.__code__):
        return [
            "{} no longer reads {} from its module; {} would not take effect".format(caller, attribute, patched.patch)
        ]
    return []


# Instructions that read a name from the module globals; co_names also lists attribute and imported names.
_GLOBAL_LOADS = frozenset(("LOAD_GLOBAL", "LOAD_NAME", "LOAD_FROM_DICT_OR_GLOBALS"))


def _global_names(code):
    """Returns the names that code, including its nested functions, reads from its module's globals."""
    names = {instruction.argval for instruction in dis.get_instructions(code) if instruction.opname in _GLOBAL_LOADS}
    for constant in code.co_consts:
        if inspect.iscode(constant):
            names |= _global_names(constant)
    return names


def _inherited_violations(owner, attribute):
    try:
        cls = resolve(owner)
    except LookupError:
        return ["{} no longer exists".format(owner)]
    if attribute in vars(cls):
        return ["{} now overrides {}, which release mode patches in its base class".format(owner, attribute)]
    return []


def _signature_violations(name, expected):
    try:
        actual = parameters(resolve(name))
    except LookupError:
        return ["{} no longer exists; release mode calls it".format(name)]
    if actual != expected:
        return ["{} parameters changed from ({}) to ({}); release mode calls it".format(name, expected, actual)]
    return []


def _field_violations(owner, names):
    try:
        cls = resolve(owner)
    except LookupError:
        return ["{} no longer exists".format(owner)]
    fields = {field.name for field in dataclasses.fields(cls)}
    return ["{} has no field {}; release mode reads it".format(owner, name) for name in names if name not in fields]
