# RT-017 retained orchestration failures and corrections

1. The initial stop command used an escaped shell variable for the target path. The VM did stop,
   but the NBD-free check printed an unreliable wrapper value. Read-only follow-up confirmed the
   VM was `shut off`, NBD was free, and the target directory was absent. No storage write occurred.

2. The first qcow2 copy command used the same escaped target variable and failed immediately with
   `cp: cannot create regular file ... No such file or directory`. The source size was checked
   afterward and no target file existed. The corrected command used the explicit target path and
   copied the qcow2 successfully.

3. The first NBD partition inspection reported `/dev/nbd15` as 0B. Follow-up read-only inspection
   showed qemu-nbd was still attached, kernel partition discovery completed asynchronously, and
   p1/p2 were available. The `qemu-nbd --list` helper itself tried its default socket and returned
   `Connection refused`; it was not used as the attachment result. The partitions were then
   mounted read-only, p2 with `noload`, extracted, unmounted, and disconnected.

No source qcow2 replacement, VM XML mutation, duplicate domain definition, or destructive storage
operation was performed. These anomalies remain retained rather than filtered.
