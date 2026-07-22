from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
BACKUP_SCRIPT = (ROOT / "backup_n8n.ps1").read_text(encoding="utf-8")
RESTORE_SCRIPT = (ROOT / "restore_n8n.ps1").read_text(encoding="utf-8")


class N8nOperationsScriptTests(unittest.TestCase):
    def test_backup_uses_temporary_file_validation_and_narrow_retention(self):
        self.assertIn('$TemporaryBackupPath = "$FinalBackupPath.tmp"', BACKUP_SCRIPT)
        self.assertIn('"pg_restore", "--list"', BACKUP_SCRIPT)
        self.assertIn('-Filter "n8n_*.dump"', BACKUP_SCRIPT)
        self.assertIn('$_.FullName -ne $CreatedBackup.FullName', BACKUP_SCRIPT)
        self.assertLess(BACKUP_SCRIPT.index("Move-Item"), BACKUP_SCRIPT.index("Get-ChildItem"))

    def test_restore_requires_confirmation_and_has_non_destructive_dry_run(self):
        confirmation = "if (-not $DryRun -and -not $ConfirmRestore)"
        self.assertIn(confirmation, RESTORE_SCRIPT)
        self.assertIn("exit 2", RESTORE_SCRIPT[RESTORE_SCRIPT.index(confirmation):])
        self.assertLess(RESTORE_SCRIPT.index(confirmation), RESTORE_SCRIPT.index('"stop", "n8n"'))
        self.assertLess(RESTORE_SCRIPT.index(confirmation), RESTORE_SCRIPT.index('Invoke-Compose -ComposeArguments @("cp"'))
        self.assertLess(RESTORE_SCRIPT.index("if ($DryRun)"), RESTORE_SCRIPT.index('"stop", "n8n"'))
        self.assertIn("if ($ContainerFileCopied", RESTORE_SCRIPT)
        self.assertIn('"pg_restore", "--list"', RESTORE_SCRIPT)
        self.assertIn("--clean --if-exists", RESTORE_SCRIPT)
        self.assertIn("--single-transaction", RESTORE_SCRIPT)

    def test_restore_error_always_requests_start_after_n8n_was_stopped(self):
        catch_start = RESTORE_SCRIPT.index("catch {")
        finally_start = RESTORE_SCRIPT.index("finally {", catch_start)
        catch_block = RESTORE_SCRIPT[catch_start:finally_start]

        self.assertNotIn("N8nStartAttempted", RESTORE_SCRIPT)
        self.assertIn("if ($N8nStopped)", catch_block)
        self.assertIn(
            "& docker compose --env-file $EnvFile up -d n8n 2>$null | Out-Null",
            catch_block,
        )
        self.assertIn("A best-effort n8n start was requested", catch_block)
        self.assertIn('Write-Error "n8n restore failed:', catch_block)
        self.assertIn("exit 1", catch_block)

    def test_scripts_do_not_reference_or_print_database_passwords(self):
        combined = BACKUP_SCRIPT + RESTORE_SCRIPT
        self.assertNotIn("N8N_POSTGRES_PASSWORD", combined)
        self.assertIsNone(re.search(r"Write-(Host|Output|Warning).*PASSWORD", combined, re.I))


if __name__ == "__main__":
    unittest.main()
