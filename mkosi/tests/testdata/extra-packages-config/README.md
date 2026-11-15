# Extra packages configuration fixture

This release configuration installs `rules-mkosi-hello` and `netbase` from `extra_packages`, built by the `test_deb_package` fixtures in [`extra_packages_test.bzl`](../../extra_packages_test.bzl).
The extra `netbase` has a lower version than the built-in snapshot's, so the image proves that an extra package replaces a snapshot package of the same name.
