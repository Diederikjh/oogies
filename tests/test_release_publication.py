"""Publication identity/gates and failure handling, without registry writes."""

import contextlib
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import publish_release as release

REVISION = "a" * 40
IMAGE_ID = "sha256:" + "b" * 64
DIGEST = "sha256:" + "c" * 64


class ReleasePublicationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name)
        self.target = release.release_target("Example/Oogies", "refs/tags/v1.2.3-rc.1", REVISION)
        self.build = {key:self.target[key] for key in ("version","revision","tag","source_url")}
        self.build.update(image_id=IMAGE_ID,dirty=False,sdk_profile=release.DEFAULT_SDK_ID,
                          sdk_archive_sha256=release.SDK_SHA256,platform="linux/amd64")
        self.artifact = {key:self.build[key] for key in ("image_id","version","revision","sdk_profile","dirty")}
        self.artifact.update(passed=True,login_calls=0,runtime_compiler=False,sdk_decoder_check=True,
            non_root=True,http_ready=True,bundled_sources_match_manifest=True,synthetic_h264_encoded=True,
            graceful_stop=True,external_state_verified=True)
        self.host = dict(image_id=IMAGE_ID,passed=True,login_calls=0,compose_contract=True,
            process_restart_verified=True,graceful_stop=True,persistence_verified=True,network_disabled=True)
        for name, report in (("last-build.json",self.build),("last-check.json",self.artifact),("last-host-check.json",self.host)):
            (self.output / name).write_text(json.dumps(report))
        self.reference = self.target["image"]+"@"+DIGEST

    def test_targets_use_lowercase_registry_names_and_deliberate_versions(self):
        self.assertEqual(self.target["tag"],"ghcr.io/example/oogies:1.2.3-rc.1")
        self.assertEqual(self.target["source_url"],"https://github.com/Example/Oogies")
        self.assertEqual(release.release_target("owner/repo","refs/tags/v0.0.1",REVISION)["version"],"0.0.1")
        for ref in ("refs/heads/main","refs/tags/latest","refs/tags/v1.2","refs/tags/v01.2.3",
                    "refs/tags/v1.2.3+build","refs/tags/v1.2.3-01","refs/tags/v1.2.3\nINJECT=value"):
            with self.subTest(ref=ref), self.assertRaises(ValueError): release.release_target("owner/repo",ref,REVISION)
        for repo in ("owner/repo/extra","../repo","owner/--bad","owner/repo\nINJECT=value"):
            with self.subTest(repo=repo), self.assertRaises(ValueError): release.release_target(repo,self.target["ref"],REVISION)
        with self.assertRaises(ValueError): release.release_target("owner/repo",self.target["ref"],"short")

    def test_source_requires_clean_checkout_and_matching_tag_commit(self):
        for values, accepted in (([REVISION,REVISION,b""],True), ([REVISION,REVISION,b" M changed"],False),
                                  (["d"*40,REVISION],False), ([REVISION,"d"*40],False)):
            with self.subTest(values=values), patch.object(release.subprocess,"check_output",side_effect=values):
                if accepted: release.require_source(self.output,self.target)
                else:
                    with self.assertRaises(ValueError): release.require_source(self.output,self.target)

    def test_failed_stale_or_incomplete_reports_cannot_qualify_an_image(self):
        self.assertEqual(release.validate_reports(self.target,self.build,self.artifact,self.host),IMAGE_ID)
        cases = [(0,"dirty",True),(0,"source_url","https://github.com/other/repo"),(0,"revision","d"*40),
                 (0,"sdk_archive_sha256","wrong"),(0,"version","1.2.4"),(0,"platform","linux/arm64"),
                 (1,"passed",False),(1,"image_id","sha256:"+"d"*64),(1,"login_calls",1),
                 (1,"dirty",True),(1,"runtime_compiler",True),(1,"bundled_sources_match_manifest",False),
                 (1,"sdk_profile","different"),(2,"passed",False),(2,"image_id","sha256:"+"d"*64),
                 (2,"network_disabled",False),(2,"process_restart_verified",False),(2,"login_calls",1)]
        for index,key,value in cases:
            reports = copy.deepcopy([self.build,self.artifact,self.host]); reports[index][key]=value
            with self.subTest(index=index,key=key), self.assertRaises(ValueError):
                release.validate_reports(self.target,*reports)

    def test_docker_identity_platform_and_labels_are_checked(self):
        labels = {"org.opencontainers.image.version":self.target["version"],
                  "org.opencontainers.image.revision":REVISION,"org.opencontainers.image.source":self.target["source_url"],
                  "oogies.sdk-profile":release.DEFAULT_SDK_ID}
        valid = dict(Id=IMAGE_ID,Os="linux",Architecture="amd64",Config={"Labels":labels})
        for key,value in ((None,None),("Id","sha256:"+"d"*64),("Architecture","arm64"),("Config",{"Labels":{}})):
            inspected=copy.deepcopy(valid)
            if key: inspected[key]=value
            with self.subTest(key=key), patch.object(release.subprocess,"check_output",return_value=json.dumps([inspected])):
                if key:
                    with self.assertRaises(ValueError): release.inspect_image(IMAGE_ID,self.target)
                else: release.inspect_image(IMAGE_ID,self.target)

    def test_push_promotes_exact_id_and_records_registry_digest(self):
        missing=subprocess.CompletedProcess([],1,"","no such manifest")
        tagged=subprocess.CompletedProcess([],0,"","")
        pushed=subprocess.CompletedProcess([],0,"1.2.3: digest: "+DIGEST+" size: 999\n","")
        with patch.object(release.subprocess,"run",side_effect=[missing,tagged,pushed]) as execute:
            self.assertEqual(release.push_image(IMAGE_ID,self.target["tag"],self.output),self.reference)
        self.assertEqual(execute.call_args_list[1].args[0],["docker","tag",IMAGE_ID,self.target["tag"]])
        self.assertEqual(execute.call_args_list[2].args[0],["docker","push",self.target["tag"]])

    def test_existing_version_and_registry_errors_refuse_tag_and_push(self):
        for status,error in ((0,""),(1,"unauthorized"),(1,"connection refused")):
            with self.subTest(error=error), patch.object(release.subprocess,"run",return_value=subprocess.CompletedProcess([],status,"",error)) as execute:
                with self.assertRaises(ValueError): release.push_image(IMAGE_ID,self.target["tag"],self.output)
                self.assertEqual(execute.call_count,1)

    def test_bad_push_output_and_failed_upload_do_not_claim_publication(self):
        for status,output in ((0,"no digest"),(1,"upload failed")):
            results=[subprocess.CompletedProcess([],1,"","manifest unknown"),subprocess.CompletedProcess([],0),subprocess.CompletedProcess([],status,output,"")]
            with self.subTest(status=status), patch.object(release.subprocess,"run",side_effect=results):
                with self.assertRaises((ValueError,subprocess.CalledProcessError)):
                    release.push_image(IMAGE_ID,self.target["tag"],self.output)

    def test_publication_pulls_digest_then_checks_that_artifact_without_rebuild(self):
        with patch.object(release,"require_source") as source, patch.object(release,"inspect_image") as inspect, \
                patch.object(release,"push_image",return_value=self.reference) as push, \
                patch.object(release.subprocess,"check_output",return_value=IMAGE_ID+"\n"), \
                patch.object(release.subprocess,"run") as execute:
            report=release.publish(self.target,self.output)
        source.assert_called_once(); inspect.assert_called_once_with(IMAGE_ID,self.target)
        push.assert_called_once_with(IMAGE_ID,self.target["tag"],self.output)
        calls=[call.args[0] for call in execute.call_args_list]
        self.assertEqual(calls[0],["docker","pull",self.reference])
        self.assertEqual([Path(call[1]).name for call in calls[1:]],["check_release_image.py","check_host_release.py"])
        self.assertTrue(all(call[-2:]==["--image",self.reference] for call in calls[1:]))
        self.assertTrue(report["verified_after_pull"])
        self.assertEqual(report["digest"],DIGEST)

    def test_mismatched_check_prevents_publication(self):
        self.artifact["image_id"]="sha256:"+"d"*64
        (self.output / "last-check.json").write_text(json.dumps(self.artifact))
        with patch.object(release,"require_source"), patch.object(release,"push_image") as push:
            with self.assertRaises(ValueError): release.publish(self.target,self.output)
            push.assert_not_called()

    def test_published_digest_is_retained_when_pull_or_post_push_check_fails(self):
        for failure in ("pull","identity","check"):
            def execute(command,**kwargs):
                if failure=="pull" or failure=="check" and command[0]==sys.executable:
                    raise subprocess.CalledProcessError(1,command)
            with self.subTest(failure=failure), patch.object(release,"require_source"), patch.object(release,"inspect_image"), \
                    patch.object(release,"push_image",return_value=self.reference), \
                    patch.object(release.subprocess,"run",side_effect=execute), \
                    patch.object(release.subprocess,"check_output",return_value="sha256:"+"d"*64 if failure=="identity" else IMAGE_ID):
                with self.assertRaises((ValueError,subprocess.CalledProcessError)): release.publish(self.target,self.output)
            report=json.loads((self.output / "publication.json").read_text())
            self.assertEqual(report["reference"],self.reference); self.assertFalse(report["verified_after_pull"])

    def test_cli_refuses_publication_outside_tag_push_context(self):
        with patch.dict(os.environ,{},clear=True), contextlib.redirect_stderr(io.StringIO()), patch.object(release,"publish") as publish:
            with self.assertRaises(SystemExit) as error: release.main(["publish"])
            self.assertEqual(error.exception.code,1); publish.assert_not_called()

    def test_prepare_writes_the_workflow_outputs_and_exact_target(self):
        environment = dict(GITHUB_ACTIONS="true",GITHUB_EVENT_NAME="push",GITHUB_REPOSITORY="Example/Oogies",
            GITHUB_REF=self.target["ref"],GITHUB_SHA=REVISION,GITHUB_OUTPUT=str(self.output / "outputs"))
        with patch.dict(os.environ,environment,clear=True), patch.object(release,"ROOT",self.output), \
                patch.object(release,"require_source") as source, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(release.main(["prepare"]),0)
        source.assert_called_once_with(self.output,self.target)
        state=self.output / ".local/releases/target.json"
        self.assertEqual(json.loads(state.read_text()),self.target)
        outputs=dict(line.split("=",1) for line in (self.output / "outputs").read_text().splitlines())
        self.assertEqual(outputs,{name:self.target[name] for name in ("version","image","source_url")})

    def test_cli_rejects_changed_target_before_publishing(self):
        environment = dict(GITHUB_ACTIONS="true",GITHUB_EVENT_NAME="push",GITHUB_REPOSITORY="Example/Oogies",
            GITHUB_REF=self.target["ref"],GITHUB_SHA=REVISION)
        state=self.output / ".local/releases"; state.mkdir(parents=True)
        (state / "target.json").write_text(json.dumps({**self.target,"revision":"d"*40}))
        with patch.dict(os.environ,environment,clear=True), patch.object(release,"ROOT",self.output), \
                patch.object(release,"publish") as publish, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error: release.main(["publish"])
            self.assertEqual(error.exception.code,1); publish.assert_not_called()
