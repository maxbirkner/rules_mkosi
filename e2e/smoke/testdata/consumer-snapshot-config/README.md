# Consumer snapshot configuration fixture

This release configuration installs `amd64-microcode`, which Debian publishes
only in the `non-free-firmware` component. `Repositories=non-free-firmware`
selects that component from the consumer-owned `@consumer_debian` snapshot.
