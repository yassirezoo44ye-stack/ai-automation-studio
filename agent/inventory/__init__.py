"""
Flow Device Agent — read-only device inventory (device advisor, M1).

Collects a small, fixed-shape snapshot of the machine so the Flow web UI can
show device health: installed applications, disk space, memory, the largest
processes and the Recycle Bin size.

PRIVACY:
  - Opt-in only: nothing is collected unless the user ran
    `flow-agent inventory on` on this device.
  - No file names, paths, window titles, browser history or document content.
  - Read-only: this package never changes anything on the device.
"""
