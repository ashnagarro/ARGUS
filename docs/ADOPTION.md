# Adopt ARGUS in your team in 5 minutes

1. Install a reviewed ARGUS Git revision with Python 3.12 or newer. Replace the
   placeholder with your organization's trusted Git URL and commit ID.

   ```powershell
   python -m pip install "git+https://YOUR-ORG/ARGUS.git@REVIEWED-COMMIT"
   argus --help
   ```

2. From your team's infrastructure repository, create the overlay:

   ```powershell
   argus init
   ```

   Create or edit `argus.toml` in the team repository to enable the optional
   overlay:

   ```toml
   [flags]
   team_overlays = true
   ```

   Edit `.argus/team.toml`. Add required tags, approved regions, approved
   owners, and enabled packs. The baseline pack always runs. A team can make
   requirements stricter, but cannot disable a baseline rule or lower its
   severity. A dated exception with owner and ticket belongs in
   `exceptions.yaml` and remains visible in the result. Setting required tags
   or approved regions automatically activates the governance pack. Organization
   instance-class and retention thresholds activate it as well.

3. Generate a Terraform plan JSON with your normal Terraform workflow:

   ```powershell
   terraform plan -out=tfplan
   terraform show -json tfplan > plan.json
   argus check plan.json
   ```

   Exit code 0 means GO or GO-WITH-CONDITIONS, 1 means NO-GO, and 2 means
   ARGUS needs a person to review the run or configuration. A CI job should
   fail on either nonzero result.

4. Copy the appropriate template from `templates/ci/` into your repository.
   Set `ARGUS_GIT_SOURCE` to a reviewed Git revision and arrange for a prior
   step to generate `plan.json`. Each template runs `argus check` and lets a
   NO-GO fail the job.

5. Review a learned team rule with its positive and negative tests. After
   approval, run `argus promote RULE_ID` to copy both into the AWS core pack.
   Review the printed checklist and run tests. From a separate team repository,
   submit the generated `packs/aws-core/` rule, test, and manifest to the
   central ARGUS repository for review. Central maintainers sync the approved
   rule and manifest into `argus/assets/packs/aws-core/` before building a new
   wheel. Promotion never overwrites an existing pack rule or writes into an
   installed package directory.

## Compare two synthetic teams

The two examples inspect the same harmless tag update. The analytics overlay
accepts it; payments requires an extra `cost_center` tag and reports G21.

```powershell
Push-Location examples/team-analytics
argus check ..\..\fixtures\plans\clean_change.json
Pop-Location
Push-Location examples/team-payments
argus check ..\..\fixtures\plans\clean_change.json
Pop-Location
```

The examples use synthetic data only. Each example includes an `argus.toml`
that enables the optional team overlay feature.
