# Synthetic payments team

This team requires an extra `cost_center` tag. From this directory, run:

```powershell
argus check ..\..\fixtures\plans\clean_change.json
```

The synthetic plan lacks that tag, so governance rule G21 makes the verdict NO-GO.
This example's `argus.toml` enables team overlays.
