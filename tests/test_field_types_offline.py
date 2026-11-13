"""E7: field types are part of the response shape (standard.md).

On a typed call a field of the wrong JSON type, or a required field that is missing, is an API error with status
200: never a coerced or defaulted result and never a raw TypeError. JSON null is fine for optional fields. Every
documented example response still parses. The Warmup client and the raw-JSON calls are exempt.
"""

import importlib
import json
import pkgutil
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import zerobouncesdk
from tests.test_transport_guards_offline import KEY, StrictJsonCorpusTest, _file_reply, _quiet, client_calls
from zerobouncesdk import ZBApiException, ZBValidateBatchElement, ZeroBounce

_ = [importlib.import_module(f"zerobouncesdk.{m.name}") for m in pkgutil.iter_modules(zerobouncesdk.__path__)]
from zerobouncesdk._zb_response import INT, ZBFieldTypeError, ZBResponse  # noqa: E402


def _models():
    found, todo = [], list(ZBResponse.__subclasses__())
    while todo:
        cls = todo.pop()
        found.append(cls)
        todo.extend(cls.__subclasses__())
    return found


def _annotated(cls):
    names = set()
    for klass in cls.__mro__:
        if klass in (ZBResponse, object):
            continue
        names.update(n for n in getattr(klass, "__annotations__", {}) if not n.startswith("_"))
    return names


def _valid_value(kinds):
    for kind, value in ((str, "5"), (bool, True), (int, 5), (float, 5.5), (list, [])):
        if kind in kinds:
            return value
    raise AssertionError(kinds)


def _wrong_values(kinds):
    """A JSON value of every type the field does not allow (5.5 for an integer field)."""
    out = []
    for value in ({}, "x", True, 5, 5.5, [1]):
        if isinstance(value, bool):
            ok = bool in kinds
        elif isinstance(value, float):
            ok = float in kinds
        elif isinstance(value, list):
            # A string-or-array field wants strings; arrays of objects are checked by the item class.
            ok = list in kinds and str not in kinds
        else:
            ok = isinstance(value, kinds)
        if not ok:
            out.append(value)
    if kinds is INT:
        assert 5.5 in out
    return out


def _minimal(cls):
    data = {name: _valid_value(cls._FIELD_TYPES[name]) for name in cls._required_fields({})}
    if "Credits" in data:
        data["Credits"] = "5"
    return data


class ModelCompletenessTest(TestCase):
    def test_the_walk_finds_the_models(self):
        names = {cls.__name__ for cls in _models()}
        self.assertLessEqual(
            {"ZBGetCreditsResponse", "ZBValidateResponse", "ZBValidateBatchResponse", "ZBValidateBatchEmail",
             "ZBValidateBatchError", "ZBFileStatusResponse", "ZBSendFileResponse", "ZBDeleteFileResponse",
             "ZBGuessFormatResponse", "ZBDomainFormat", "ZBFindEmailFormatResponse", "ZBFindDomainResponse",
             "ZBGetActivityResponse", "ZBGetApiUsageResponse", "ZBScoreEmailResponse", "ZBListEvaluatorResponse"},
            names,
        )

    def test_every_field_of_every_model_has_a_json_type(self):
        missing = []
        for cls in _models():
            typed = set(cls._FIELD_TYPES) | set(cls._SDK_FIELDS)
            missing += [(cls.__name__, name) for name in sorted(_annotated(cls) - typed)]
        self.assertEqual(missing, [])

    def test_every_field_rejects_every_other_json_type(self):
        accepted = []
        for cls in _models():
            for name, kinds in cls._FIELD_TYPES.items():
                for wrong in _wrong_values(kinds):
                    data = {**_minimal(cls), name: wrong}
                    try:
                        cls.check_shape(data)
                    except ZBFieldTypeError:
                        continue
                    accepted.append((cls.__name__, name, wrong))
        self.assertEqual(accepted, [])

    def test_null_is_fine_for_every_optional_field(self):
        for cls in _models():
            required = cls._required_fields({})
            for name in cls._FIELD_TYPES:
                if name not in required:
                    cls.check_shape({**_minimal(cls), name: None})

    def test_array_items_are_checked(self):
        for cls in _models():
            for name, item_class in cls._ITEMS.items():
                with self.assertRaises(ZBFieldTypeError, msg=(cls.__name__, name)):
                    cls.check_shape({**_minimal(cls), name: [5]})
                with self.assertRaises(ZBFieldTypeError, msg=(cls.__name__, name)):
                    field = next(iter(item_class._FIELD_TYPES))
                    cls.check_shape({**_minimal(cls), name: [{**_minimal(item_class), field: {}}]})


class TypedCallSweepTest(TestCase):
    """Every typed call (one that returns a model) rejects a body whose fields all have the wrong type."""

    DOWNLOADS = StrictJsonCorpusTest.DOWNLOADS

    def _calls(self):
        out = str(Path(tempfile.mkdtemp()) / "out.csv")
        calls = client_calls(ZeroBounce(KEY), out)
        return [(name, call) for name, variants in calls.items() for call in variants if name not in self.DOWNLOADS]

    def _all_fields(self):
        fields = {}
        for cls in _models():
            fields.update(cls._FIELD_TYPES)
        return fields

    def test_every_typed_call_checks_its_fields(self):
        fields = self._all_fields()
        # Null everywhere, the required fields valid, no message keys (a bare message is a rejection elsewhere).
        good = {name: None for name in fields if name.lower() != "message"}
        good.update({"Credits": "5", "address": "a@example.com", "status": "valid"})
        bad = {name: {} for name in fields}
        typed, wrong = set(), []
        for name, call in self._calls():
            with patch("requests.sessions.Session.send", _file_reply(200, json.dumps(good).encode(), "application/json")):
                try:
                    result = _quiet(call)
                except ZBApiException:
                    continue
            if not isinstance(result, ZBResponse):
                continue
            typed.add(name)
            with patch("requests.sessions.Session.send", _file_reply(200, json.dumps(bad).encode(), "application/json")):
                try:
                    _quiet(call)
                except ZBApiException as error:
                    if error.status_code != 200 or "unexpected shape" not in str(error):
                        wrong.append((name, error.status_code, str(error)))
                else:
                    wrong.append((name, "accepted"))
        self.assertGreater(len(typed), 20)
        self.assertLessEqual({"get_credits", "validate", "validate_batch", "file_status", "send_file", "guess_format", "find_domain",
             "get_api_usage", "score_email", "get_list_evaluator_result"}, typed)
        self.assertEqual(wrong, [])


class CreditsAndValidateTest(TestCase):
    """The cases checks.md E7 names, on GET and POST."""

    def _error(self, call, body):
        with patch("requests.sessions.Session.send", _file_reply(200, body.encode(), "application/json")):
            with self.assertRaises(ZBApiException, msg=body) as caught:
                call()
        self.assertEqual(caught.exception.status_code, 200, body)
        self.assertIn("unexpected shape", str(caught.exception), body)

    def _ok(self, call, body):
        with patch("requests.sessions.Session.send", _file_reply(200, body.encode(), "application/json")):
            return call()

    def test_credits_must_be_an_integer_as_a_json_string_or_number(self):
        client = ZeroBounce(KEY)
        for use_post in (False, True):
            call = lambda: client.get_credits(use_post=use_post)  # noqa: E731
            for body in ('{}', '{"Credits":null}', '{"Credits":true}', '{"Credits":false}', '{"Credits":5.5}',
                         '{"Credits":5.0}', '{"Credits":1e3}', '{"Credits":"abc"}', '{"Credits":"5.0"}',
                         '{"Credits":""}', '{"Credits":" 5"}', '{"Credits":[1]}', '{"Credits":{"a":1}}',
                         '{"Credits":"٥"}'):
                self._error(call, body)
            # The live API sends a JSON string; zerobounce.net's example sends a JSON number. Both are kept as sent.
            self.assertEqual(self._ok(call, '{"Credits":"-1"}').credits, "-1")
            self.assertEqual(self._ok(call, '{"Credits":"12345"}').credits, "12345")
            self.assertEqual(self._ok(call, '{"Credits":2375323}').credits, 2375323)
            self.assertEqual(self._ok(call, '{"Credits":-1}').credits, -1)
            self.assertEqual(self._ok(call, '{"Credits":0}').credits, 0)

    def test_validate_needs_a_string_address_and_status(self):
        client = ZeroBounce(KEY)
        for use_post in (False, True):
            call = lambda: client.validate("a@example.com", use_post=use_post)  # noqa: E731
            for body in ('{"address":true,"status":"valid"}', '{"address":"a@b.c","status":5}',
                         '{"address":"a@b.c"}', '{"status":"valid"}', '{"address":null,"status":"valid"}',
                         '{"address":"a@b.c","status":"valid","free_email":5}',
                         '{"address":"a@b.c","status":"valid","domain_age_days":9692}',
                         '{}'):
                self._error(call, body)
            # An unknown status string is kept, not rejected.
            with self.assertWarns(UserWarning):
                result = self._ok(call, '{"address":"a@b.c","status":"brand_new"}')
            self.assertEqual(result.raw_status, "brand_new")

    def test_batch_rows_are_checked(self):
        client = ZeroBounce(KEY)
        call = lambda: client.validate_batch([ZBValidateBatchElement("a@example.com")])  # noqa: E731
        for body in ('{"email_batch":[{"address":"a@b.c","status":5}],"errors":[]}',
                     '{"email_batch":[{"status":"valid"}],"errors":[]}',
                     '{"email_batch":[{"address":"a@b.c"}],"errors":[]}',
                     '{"email_batch":[{"address":null,"status":"valid"}],"errors":[]}',
                     '{"email_batch":[{"address":"a@b.c","status":null}],"errors":[]}',
                     '{"email_batch":[5],"errors":[]}',
                     '{"email_batch":[null],"errors":[]}',
                     '{"email_batch":["a@b.c"],"errors":[]}',
                     '{"email_batch":[["a@b.c","valid"]],"errors":[]}',
                     '{"email_batch":[],"errors":[5]}',
                     '{"email_batch":[],"errors":[null]}',
                     '{"email_batch":[],"errors":[{"error":5,"email_address":"a@b.c"}]}'):
            self._error(call, body)


# Recorded response shapes (the live API, the repo's fixtures and older docs): they must all parse. The examples
# zerobounce.net/docs shows today are in SITE_RESULTS below, verbatim.
DOCUMENTED = {
    "get_credits": '{"Credits":"2375323"}',
    "validate": (
        '{"address":"flowerjill@aol.com","status":"valid","sub_status":"","free_email":true,"did_you_mean":null,'
        '"account":"flowerjill","domain":"aol.com","domain_age_days":"9692","active_in_days":"180",'
        '"smtp_provider":"yahoo","mx_found":"true","mx_record":"mx-aol.mail.gm0.yahoodns.net","firstname":"Jill",'
        '"lastname":"Stein","gender":"female","country":"United States","region":"Florida",'
        '"city":"West Palm Beach","zipcode":"33401","processed_at":"2017-04-01 02:48:02.592"}'
    ),
    "validate_greylist": '{"Message":"Greylist validation still in progress..."}',
    "validate_batch": (
        '{"email_batch":[{"address":"valid@example.com","status":"valid","sub_status":"","free_email":false,'
        '"did_you_mean":null,"account":null,"domain":null,"domain_age_days":"9692","active_in_days":"180",'
        '"smtp_provider":"example","mx_found":"true","mx_record":"mx.example.com","firstname":"zero",'
        '"lastname":"bounce","gender":"male","country":null,"region":null,"city":null,"zipcode":null,'
        '"processed_at":"2020-09-17 17:43:11.829"}],"errors":[]}'
    ),
    "get_api_usage": (
        '{"total":3,"status_valid":1,"status_invalid":2,"status_catch_all":0,"status_do_not_mail":0,'
        '"status_spamtrap":0,"status_unknown":0,"sub_status_toxic":0,"sub_status_disposable":0,'
        '"sub_status_role_based":0,"sub_status_possible_trap":0,"sub_status_global_suppression":0,'
        '"sub_status_timeout_exceeded":0,"sub_status_mail_server_temporary_error":0,'
        '"sub_status_mail_server_did_not_respond":0,"sub_status_greylisted":0,"sub_status_antispam_system":0,'
        '"sub_status_does_not_accept_mail":0,"sub_status_exception_occurred":0,"sub_status_failed_syntax_check":0,'
        '"sub_status_mailbox_not_found":2,"sub_status_unroutable_ip_address":0,"sub_status_possible_typo":0,'
        '"sub_status_no_dns_entries":0,"sub_status_role_based_catch_all":0,"sub_status_mailbox_quota_exceeded":0,'
        '"sub_status_forcible_disconnect":0,"sub_status_failed_smtp_connection":0,"sub_status_mx_forward":0,'
        '"sub_status_alternate":0,"sub_status_blocked":0,"sub_status_allowed":0,'
        '"start_date":"4/1/2018","end_date":"9/9/2019"}'
    ),
    "get_activity": '{"found":true,"active_in_days":"180"}',
    "score_email": '{"email":"valid@example.com","score":10}',
    "send_file": '{"success":true,"message":"File Accepted","file_name":"Your file name.csv",'
                 '"file_id":"aaaaaaaa-zzzz-xxxx-yyyy-5003727fffff"}',
    "file_status": '{"success":true,"file_id":"84946fc8-3f89-428a-9d0d-382fbe18cb24","file_name":"validation.csv",'
                   '"upload_date":"2025-10-16T08:28:37Z","file_status":"Processing","complete_percentage":"0%",'
                   '"error_reason":null,"return_url":null}',
    "delete_file": '{"success":true,"message":"File Deleted","file_name":"test2","file_id":"b222a0fd-90d5-416c-8f1a-9cc3851fc823"}',
    "guess_format": (
        '{"email":"john.doe@example.com","domain":"example.com","format":"first.last","status":"valid",'
        '"sub_status":"","confidence":"high","did_you_mean":"","failure_reason":"",'
        '"other_domain_formats":[{"format":"first_last","confidence":"high"},{"format":"first","confidence":"medium"}]}'
    ),
    "find_email_format": '{"email":"john.doe@example.com","email_confidence":"HIGH","domain":"example.com",'
                         '"company_name":"Example","did_you_mean":"","failure_reason":""}',
    "find_domain": '{"domain":"example.com","company_name":"Example","format":"first.last","confidence":"high",'
                   '"did_you_mean":"","failure_reason":"","other_domain_formats":[{"format":"first","confidence":"low"}]}',
    "get_list_evaluator_result": '{"file_id":"ev-1","status":"finished","progress":100,"invalid_percentage":4.2,'
                                 '"catch_all_percentage":0,"activity_data_percentage":0,"abuse":true,'
                                 '"do_not_mail":false,"spam_trap":false,"total_risky_percentage":0,"error_message":""}',
}


class DocumentedExamplesParseTest(TestCase):
    def test_every_documented_example_parses(self):
        out = str(Path(tempfile.mkdtemp()) / "out.csv")
        calls = client_calls(ZeroBounce(KEY), out)
        aliases = {"validate_greylist": "validate"}
        for example, body in DOCUMENTED.items():
            name = aliases.get(example, example)
            self.assertIn(name, calls, example)
            for call in calls[name]:
                with patch("requests.sessions.Session.send", _file_reply(200, body.encode(), "application/json")):
                    result = _quiet(call)
                self.assertIsInstance(result, ZBResponse, example)


# Example responses copied verbatim from zerobounce.net/docs (the page each one is on is named above it).
# Success examples must parse; the documented error examples must be API errors with status 200.
SITE_RESULTS = [
    # _ai-scoring-api_ai-scoring-api__file-status_api-file-status-response.html
    ('scoring_file_status', (
        '{\n'
        '          "success": true,\n'
        '          "file_id": "aaaaaaaa-zzzz-xxxx-yyyy-5003727fffff",\n'
        '          "file_name": "Your file name.csv",\n'
        '          "upload_date": "2023-04-28T15:25:41Z",\n'
        '          "file_status": "Complete",\n'
        '          "complete_percentage": "100%",\n'
        '          "return_url": "Your return URL if provided when calling sendfile API"\n'
        '      }'
    )),
    # _ai-scoring-api_ai-scoring-api__send-file_api-send-file-response.html
    ('scoring_send_file', (
        '{\n'
        '          "success": true,\n'
        '          "message": "File Accepted",\n'
        '          "file_name": "Your file name.csv",\n'
        '          "file_id": "aaaaaaaa-zzzz-xxxx-yyyy-5003727fffff"\n'
        '      }'
    )),
    # _ai-scoring-api_ai_scoring_delete_file_scoring__delete-file.html
    ('scoring_delete_file', (
        '{\n'
        '        "success": true,\n'
        '        "message": "File Deleted",\n'
        '        "file_name": "test2",\n'
        '        "file_id": "b222a0fd-90d5-416c-8f1a-9cc3851fc823"\n'
        '    }'
    )),
    # _email-validation-api-quickstart_v2-credit-balance_response.html
    ('get_credits', (
        '{"Credits":2375323}'
    )),
    # _email-validation-api-quickstart_v2-delete-file_response.html
    ('delete_file', (
        '{\n'
        '    "success": true,\n'
        '    "message": "File Deleted",\n'
        '    "file_name": "test2",\n'
        '    "file_id": "b222a0fd-90d5-416c-8f1a-9cc3851fc823"\n'
        '  }'
    )),
    # _email-validation-api-quickstart_v2-file-status_response.html
    ('file_status', (
        '{\n'
        '    "success": true,\n'
        '    "file_id": "aaaaaaaa-zzzz-xxxx-yyyy-5003727fffff",\n'
        '    "file_name": "Your file name.csv",\n'
        '    "upload_date": "2023-04-28T15:25:41Z",\n'
        '    "file_status": "Complete",\n'
        '    "file_phase_2_status": "N/A",\n'
        '    "complete_percentage": "100%",\n'
        '    "return_url": "Your return URL if provided when calling sendfile API"\n'
        '  }'
    )),
    # _email-validation-api-quickstart_v2-file-status_response.html
    ('file_status', (
        '{\n'
        '    "success": true,\n'
        '    "file_id": "aaaaaaaa-zzzz-xxxx-yyyy-5003727fffff",\n'
        '    "file_name": "Your file name.csv",\n'
        '    "upload_date": "2023-04-28T15:25:41Z",\n'
        '    "file_status": "Complete",\n'
        '    "file_phase_2_status": "Complete",\n'
        '    "complete_percentage": "100%",\n'
        '    "return_url": "Your return URL if provided when calling sendfile API"\n'
        '  }'
    )),
    # _email-validation-api-quickstart_v2-send-file_response.html
    ('send_file', (
        '{\n'
        '      "success": true,\n'
        '      "message": "File Accepted",\n'
        '      "file_name": "Your file name.csv",\n'
        '      "file_id": "aaaaaaaa-zzzz-xxxx-yyyy-5003727fffff"\n'
        '    }'
    )),
    # _email-validation-api-quickstart_v2-validate-emails_response.html
    ('validate', (
        '{\n'
        '      "address": "john.doe@zerobounce.net",\n'
        '      "status": "valid",\n'
        '      "sub_status": "",\n'
        '      "free_email": false,\n'
        '      "catchall_domain": true,\n'
        '      "did_you_mean": null,\n'
        '      "account": "johndoe",\n'
        '      "domain": "zerobounce.net",\n'
        '      "domain_age_days": "3431",\n'
        '      "active_in_days": "30",\n'
        '      "active_first_seen": "2026-02-25",\n'
        '      "smtp_provider": "g-suite",\n'
        '      "mx_found": "true",\n'
        '      "mx_record": "aspmx.l.google.com",\n'
        '      "firstname": "dan",\n'
        '      "lastname": "cotet",\n'
        '      "gender": "male",\n'
        '      "country": null,\n'
        '      "region": null,\n'
        '      "city": null,\n'
        '      "zipcode": null,\n'
        '      "processed_at": "2026-06-18 07:05:00.033"\n'
        '  }'
    )),
]
SITE_ERRORS = [
    # _ai-scoring-api_ai-scoring-api__file-status_api-file-status-response.html
    ('scoring_file_status', (
        '{\n'
        '          "success": false,\n'
        '          "message": "Error messages"\n'
        '      }'
    )),
    # _ai-scoring-api_ai-scoring-api__send-file_api-send-file-response.html
    ('scoring_send_file', (
        '{\n'
        '          "success": false,\n'
        '          "message": [\n'
        '              "Error messages"\n'
        '          ]\n'
        '      }'
    )),
    # _ai-scoring-api_ai_scoring_delete_file_scoring__delete-file.html
    ('scoring_delete_file', (
        '{\n'
        '        "success": false,\n'
        '        "message": "File cannot be found."\n'
        '    }'
    )),
    # _email-validation-api-quickstart_v2-batch-validate-emails_response.html
    ('validate_batch', (
        '{\n'
        '      "email_batch": [],\n'
        '      "errors": [\n'
        '          {\n'
        '              "error": "Invalid API Key or your account ran out of credits",\n'
        '              "email_address": "all"\n'
        '          }\n'
        '      ]\n'
        '    }'
    )),
    # _email-validation-api-quickstart_v2-delete-file_response.html
    ('delete_file', (
        '{\n'
        '    "success": false,\n'
        '    "error_message": "File cannot be found."\n'
        '  }'
    )),
    # _email-validation-api-quickstart_v2-file-status_response.html
    ('file_status', (
        '{      \n'
        '    "success": false,\n'
        '    "error_message": "Error messages"\n'
        '  }'
    )),
    # _email-validation-api-quickstart_v2-get-api-usage_response.html
    ('get_api_usage', (
        '{"error":"Invalid API Key"}'
    )),
    # _email-validation-api-quickstart_v2-get-api-usage_response.html
    ('get_api_usage', (
        '{"error":"Invalid Date"}'
    )),
    # _email-validation-api-quickstart_v2-send-file_response.html
    ('send_file', (
        '{\n'
        '      "success": false,\n'
        '      "error_message": "Error messages"\n'
        '    }'
    )),
    # _email-validation-api-quickstart_v2-validate-emails_response.html
    ('validate', (
        '{"error":"Invalid API Key or your account ran out of credits"}'
    )),
]


class ZeroBounceNetExamplesTest(TestCase):
    def _calls(self):
        return client_calls(ZeroBounce(KEY), str(Path(tempfile.mkdtemp()) / "out.csv"))

    def test_every_documented_result_parses(self):
        calls = self._calls()
        for name, parts in SITE_RESULTS:
            body = "".join(parts)
            self.assertIn(name, calls)
            for call in calls[name]:
                with patch("requests.sessions.Session.send", _file_reply(200, body.encode(), "application/json")):
                    result = _quiet(call)
                self.assertIsInstance(result, ZBResponse, name)
        with patch("requests.sessions.Session.send", _file_reply(200, b'{"Credits":2375323}', "application/json")):
            self.assertEqual(ZeroBounce(KEY).get_credits().credits, 2375323)

    def test_every_documented_error_is_an_error_with_status_200(self):
        calls = self._calls()
        for name, parts in SITE_ERRORS:
            body = "".join(parts)
            self.assertIn(name, calls)
            for call in calls[name]:
                with patch("requests.sessions.Session.send", _file_reply(200, body.encode(), "application/json")):
                    with self.assertRaises(ZBApiException, msg=(name, body)) as caught:
                        _quiet(call)
                self.assertEqual(caught.exception.status_code, 200, (name, body))


# Documented answers with nested values (array items, rows and their fields), for the nested-path sweep.
NESTED_EXAMPLES = {
    "validate_batch": (DOCUMENTED["validate_batch"], "ZBValidateBatchResponse"),
    "guess_format": (DOCUMENTED["guess_format"], "ZBGuessFormatResponse"),
    "find_domain": (DOCUMENTED["find_domain"], "ZBFindDomainResponse"),
    "send_file": ('{"success":true,"message":["File Accepted"],"file_name":"f.csv","file_id":"f1"}', "ZBSendFileResponse"),
}


def _nested_mutations(cls, data):
    """(path, body) for every wrong JSON type at every nested path of ``data``: each array item of a typed array
    (an item of a string array that is not a string, an item of an object array that is not an object) and each
    field of each item object (a type the item's model does not allow, or null for a required field)."""
    out = []
    for name, kinds in cls._FIELD_TYPES.items():
        items = data.get(name)
        if not isinstance(items, list) or not items:
            continue
        item_class = cls._ITEMS.get(name)
        for index, item in enumerate(items):
            path = f"{name}[{index}]"
            wrong_items = ({}, 5, 5.5, True, None, [1], []) if item_class is None else ("x", 5, 5.5, True, None, [1], [])
            for wrong in wrong_items:
                out.append((path, {**data, name: items[:index] + [wrong] + items[index + 1:]}))
            if item_class is None:
                continue
            for field, field_kinds in item_class._FIELD_TYPES.items():
                wrongs = list(_wrong_values(field_kinds))
                if field in item_class._required_fields(item):
                    wrongs.append(None)
                for wrong in wrongs:
                    row = {**item, field: wrong}
                    out.append((f"{path}.{field}", {**data, name: items[:index] + [row] + items[index + 1:]}))
    return out


class NestedPathSweepTest(TestCase):
    """Every field-type guard on a nested value (array items, batch rows, their fields) is exercised end to end:
    each wrong JSON type at each nested path of a documented answer is an API error with status 200."""

    def test_every_nested_path_rejects_every_wrong_type(self):
        models = {cls.__name__: cls for cls in _models()}
        calls = client_calls(ZeroBounce(KEY), str(Path(tempfile.mkdtemp()) / "out.csv"))
        wrong, count = [], 0
        for name, (example, model) in NESTED_EXAMPLES.items():
            for call in calls[name]:
                with patch("requests.sessions.Session.send", _file_reply(200, example.encode(), "application/json")):
                    self.assertIsInstance(_quiet(call), ZBResponse, name)
                for path, data in _nested_mutations(models[model], json.loads(example)):
                    count += 1
                    body = json.dumps(data).encode()
                    with patch("requests.sessions.Session.send", _file_reply(200, body, "application/json")):
                        try:
                            result = _quiet(call)
                        except ZBApiException as error:
                            if error.status_code != 200:
                                wrong.append((name, path, error.status_code))
                        except Exception as error:  # noqa: BLE001 - a raw language error is a wrong answer
                            wrong.append((name, path, type(error).__name__))
                        else:
                            wrong.append((name, path, "accepted", body, result))
        self.assertGreater(count, 200)
        self.assertEqual(wrong, [])
