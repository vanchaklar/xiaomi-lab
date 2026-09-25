# Offline cloud-run analyzer

The cloud CSV already contains the signals needed to test whether automatic fan
boost can serve as a carpet marker, provided the firmware emitted a
`properties_changed` notification for fan speed during that run.

Use:

```bash
python experiments/analyze_cloud_run.py data/cloud_ui_YYYYMMDD_HHMMSS_REGION.csv
```

The analyzer reports:

- every fan-speed `2/6` notification and old/new value;
- vacuum status/fault at the same time;
- current clean area/time;
- nearest map packet before and after each fan transition;
- map packet/type statistics;
- type-4 challenge-cell counts;
- redraw events;
- current-clean-record events.

For the raw nearest triplets as well:

```bash
python experiments/analyze_cloud_run.py \
  data/cloud_ui_YYYYMMDD_HHMMSS_REGION.csv \
  --show-map-points
```

If the output says there are no `2/6` notifications, the existing CSV cannot
timestamp the fan boost even though other property events were captured. That
distinction matters: absence from the excerpt is not evidence that the event was
or was not present in the full file.
