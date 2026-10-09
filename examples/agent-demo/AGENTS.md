# ARGUS agent demo

Before finishing any Terraform change: run `terraform plan -out plan.out`; save `terraform show -json plan.out` as `plan.json`; call `argus_check` on `plan.json`. If the verdict is NO-GO, fix the change and re-check until GO or GO-WITH-CONDITIONS. Never bypass ARGUS.

The provider credentials and resources in this directory are synthetic and intended only for a local plan demonstration.
