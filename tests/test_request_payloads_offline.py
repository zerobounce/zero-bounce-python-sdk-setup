"""The exact request every public request method builds: verb, host, path, query and body.

JSON, form and multipart bodies are compared field by field, so a wrong field name (``old_address`` for
``old_from_address``, ``type`` for a filter's ``target``) fails here. The tables cover every public request
method of ``ZeroBounce`` and ``ZeroBounceWarmup``; a new method fails the completeness checks until it is added.
"""

import io
import os
import tempfile
import warnings
from datetime import date
from unittest import TestCase
from unittest.mock import patch

from tests.test_offline_api import RecordedRequest, _response
from zerobouncesdk import ZBGetFileOptions, ZBValidateBatchElement, ZeroBounce, ZeroBounceWarmup

D = "https://example.com/d"
NOT_REQUESTS = {"get_file_json_indicates_error"}

# name (the method, then an optional variant) -> (call, the one request it sends)
CORE = {
    'get_credits': (
        lambda c, w, f, s, out: c.get_credits(),
        {   'verb': 'GET',
            'url': 'api.zerobounce.net/v2/getcredits',
            'query': {'api_key': 'payload-key'},
            'body': None},
    ),
    'get_credits use_post': (
        lambda c, w, f, s, out: c.get_credits(use_post=True),
        {   'verb': 'POST',
            'url': 'api.zerobounce.net/v2/getcredits',
            'query': {},
            'body': {'api_key': 'payload-key'}},
    ),
    'get_api_usage': (
        lambda c, w, f, s, out: c.get_api_usage(date(2024, 1, 1), date(2024, 1, 2)),
        {   'verb': 'GET',
            'url': 'api.zerobounce.net/v2/getapiusage',
            'query': {'start_date': '2024-01-01', 'end_date': '2024-01-02', 'api_key': 'payload-key'},
            'body': None},
    ),
    'get_api_usage use_post': (
        lambda c, w, f, s, out: c.get_api_usage(date(2024, 1, 1), date(2024, 1, 2), use_post=True),
        {   'verb': 'POST',
            'url': 'api.zerobounce.net/v2/getapiusage',
            'query': {},
            'body': {'start_date': '2024-01-01', 'end_date': '2024-01-02', 'api_key': 'payload-key'}},
    ),
    'get_activity': (
        lambda c, w, f, s, out: c.get_activity('a@example.com'),
        {   'verb': 'GET',
            'url': 'api.zerobounce.net/v2/activity',
            'query': {'email': 'a@example.com', 'api_key': 'payload-key'},
            'body': None},
    ),
    'get_activity use_post': (
        lambda c, w, f, s, out: c.get_activity('a@example.com', use_post=True),
        {   'verb': 'POST',
            'url': 'api.zerobounce.net/v2/activity',
            'query': {},
            'body': {'email': 'a@example.com', 'api_key': 'payload-key'}},
    ),
    'score_email': (
        lambda c, w, f, s, out: c.score_email('a@example.com'),
        {   'verb': 'GET',
            'url': 'api.zerobounce.net/v2/scoring',
            'query': {'email': 'a@example.com', 'api_key': 'payload-key'},
            'body': None},
    ),
    'score_email use_post': (
        lambda c, w, f, s, out: c.score_email('a@example.com', use_post=True),
        {   'verb': 'POST',
            'url': 'api.zerobounce.net/v2/scoring',
            'query': {},
            'body': {'email': 'a@example.com', 'api_key': 'payload-key'}},
    ),
    'validate': (
        lambda c, w, f, s, out: c.validate('a@example.com', '1.2.3.4', timeout=10, activity_data=True, verify_plus=False, domain_info=True, greylist_processing=True, callback_url=D),
        {   'verb': 'GET',
            'url': 'api.zerobounce.net/v2/validate',
            'query': {   'email': 'a@example.com',
                         'ip_address': '1.2.3.4',
                         'timeout': '10',
                         'activity_data': 'true',
                         'verify_plus': 'false',
                         'domain_info': 'true',
                         'greylist_processing': 'true',
                         'callback_url': 'https://example.com/d',
                         'api_key': 'payload-key'},
            'body': None},
    ),
    'validate use_post': (
        lambda c, w, f, s, out: c.validate('a@example.com', '1.2.3.4', timeout=10, activity_data=True, use_post=True),
        {   'verb': 'POST',
            'url': 'api.zerobounce.net/v2/validate',
            'query': {},
            'body': {   'email': 'a@example.com',
                        'ip_address': '1.2.3.4',
                        'timeout': '10',
                        'activity_data': 'true',
                        'api_key': 'payload-key'}},
    ),
    'validate_batch': (
        lambda c, w, f, s, out: c.validate_batch([ZBValidateBatchElement('a@example.com', '1.2.3.4'), ZBValidateBatchElement('b@example.com')], timeout=30, activity_data=True, verify_plus=True),
        {   'verb': 'POST',
            'url': 'api.zerobounce.net/v2/validatebatch',
            'query': {},
            'body': {   'api_key': 'payload-key',
                        'email_batch': [   {'email_address': 'a@example.com', 'ip_address': '1.2.3.4'},
                                           {'email_address': 'b@example.com'}],
                        'timeout': '30',
                        'activity_data': True,
                        'verify_plus': True}},
    ),
    'send_file': (
        lambda c, w, f, s, out: c.send_file(f, 1, return_url=D, first_name_column=2, last_name_column=3, gender_column=4, ip_address_column=5, has_header_row=True, remove_duplicate=False, allow_phase_2=True),
        {   'verb': 'POST',
            'url': 'bulkapi.zerobounce.net/v2/sendfile',
            'query': {},
            'body': {   'return_url': 'https://example.com/d',
                        'first_name_column': '2',
                        'last_name_column': '3',
                        'gender_column': '4',
                        'ip_address_column': '5',
                        'has_header_row': 'true',
                        'remove_duplicate': 'false',
                        'allow_phase_2': 'true',
                        'api_key': 'payload-key',
                        'email_address_column': '1',
                        'file': '<file emails.csv>'}},
    ),
    'send_file unset': (
        lambda c, w, f, s, out: c.send_file(f, 1),
        {   'verb': 'POST',
            'url': 'bulkapi.zerobounce.net/v2/sendfile',
            'query': {},
            'body': {   'has_header_row': 'false',
                        'remove_duplicate': 'true',
                        'api_key': 'payload-key',
                        'email_address_column': '1',
                        'file': '<file emails.csv>'}},
    ),
    'send_file_stream': (
        lambda c, w, f, s, out: c.send_file_stream(s(), 'f.csv', 2, remove_duplicate=False),
        {   'verb': 'POST',
            'url': 'bulkapi.zerobounce.net/v2/sendfile',
            'query': {},
            'body': {   'has_header_row': 'false',
                        'remove_duplicate': 'false',
                        'api_key': 'payload-key',
                        'email_address_column': '2',
                        'file': '<file f.csv>'}},
    ),
    'scoring_send_file': (
        lambda c, w, f, s, out: c.scoring_send_file(f, 2, return_url=D, has_header_row=True, remove_duplicate=False),
        {   'verb': 'POST',
            'url': 'bulkapi.zerobounce.net/v2/scoring/sendfile',
            'query': {},
            'body': {   'return_url': 'https://example.com/d',
                        'has_header_row': 'true',
                        'remove_duplicate': 'false',
                        'api_key': 'payload-key',
                        'email_address_column': '2',
                        'file': '<file emails.csv>'}},
    ),
    'scoring_send_file_stream': (
        lambda c, w, f, s, out: c.scoring_send_file_stream(s(), 'f.csv', 1),
        {   'verb': 'POST',
            'url': 'bulkapi.zerobounce.net/v2/scoring/sendfile',
            'query': {},
            'body': {   'has_header_row': 'false',
                        'remove_duplicate': 'true',
                        'api_key': 'payload-key',
                        'email_address_column': '1',
                        'file': '<file f.csv>'}},
    ),
    'file_status': (
        lambda c, w, f, s, out: c.file_status('f1'),
        {   'verb': 'GET',
            'url': 'bulkapi.zerobounce.net/v2/filestatus',
            'query': {'file_id': 'f1', 'api_key': 'payload-key'},
            'body': None},
    ),
    'scoring_file_status': (
        lambda c, w, f, s, out: c.scoring_file_status('f1'),
        {   'verb': 'GET',
            'url': 'bulkapi.zerobounce.net/v2/scoring/filestatus',
            'query': {'file_id': 'f1', 'api_key': 'payload-key'},
            'body': None},
    ),
    'get_file': (
        lambda c, w, f, s, out: c.get_file('f1', out, ZBGetFileOptions(download_type='phase_1', activity_data=True)),
        {   'verb': 'GET',
            'url': 'bulkapi.zerobounce.net/v2/getfile',
            'query': {   'api_key': 'payload-key',
                         'file_id': 'f1',
                         'download_type': 'phase_1',
                         'activity_data': 'true'},
            'body': None},
    ),
    'get_file stream': (
        lambda c, w, f, s, out: c.get_file('f1', out, stream=True),
        {   'verb': 'GET',
            'url': 'bulkapi.zerobounce.net/v2/getfile',
            'query': {'api_key': 'payload-key', 'file_id': 'f1'},
            'body': None},
    ),
    'scoring_get_file': (
        lambda c, w, f, s, out: c.scoring_get_file('f1', out, ZBGetFileOptions(download_type='combined')),
        {   'verb': 'GET',
            'url': 'bulkapi.zerobounce.net/v2/scoring/getfile',
            'query': {'api_key': 'payload-key', 'file_id': 'f1', 'download_type': 'combined'},
            'body': None},
    ),
    'delete_file': (
        lambda c, w, f, s, out: c.delete_file('f1'),
        {   'verb': 'GET',
            'url': 'bulkapi.zerobounce.net/v2/deletefile',
            'query': {'file_id': 'f1', 'api_key': 'payload-key'},
            'body': None},
    ),
    'scoring_delete_file': (
        lambda c, w, f, s, out: c.scoring_delete_file('f1'),
        {   'verb': 'GET',
            'url': 'bulkapi.zerobounce.net/v2/scoring/deletefile',
            'query': {'file_id': 'f1', 'api_key': 'payload-key'},
            'body': None},
    ),
    'send_email_finder_file': (
        lambda c, w, f, s, out: c.send_email_finder_file(f, 1, first_name_column=2, last_name_column=3, middle_name_column=4, has_header_row=True),
        {   'verb': 'POST',
            'url': 'bulkapi.zerobounce.net/email-finder/sendfile',
            'query': {},
            'body': {   'domain_column': '1',
                        'has_header_row': 'true',
                        'first_name_column': '2',
                        'last_name_column': '3',
                        'middle_name_column': '4',
                        'api_key': 'payload-key',
                        'file': '<file emails.csv>'}},
    ),
    'send_email_finder_file_stream': (
        lambda c, w, f, s, out: c.send_email_finder_file_stream(s(), 'f.csv', 1, full_name_column=2),
        {   'verb': 'POST',
            'url': 'bulkapi.zerobounce.net/email-finder/sendfile',
            'query': {},
            'body': {   'domain_column': '1',
                        'has_header_row': 'false',
                        'full_name_column': '2',
                        'api_key': 'payload-key',
                        'file': '<file f.csv>'}},
    ),
    'email_finder_file_status': (
        lambda c, w, f, s, out: c.email_finder_file_status('f1'),
        {   'verb': 'GET',
            'url': 'bulkapi.zerobounce.net/email-finder/filestatus',
            'query': {'file_id': 'f1', 'api_key': 'payload-key'},
            'body': None},
    ),
    'email_finder_get_file': (
        lambda c, w, f, s, out: c.email_finder_get_file('f1', out),
        {   'verb': 'GET',
            'url': 'bulkapi.zerobounce.net/email-finder/getfile',
            'query': {'api_key': 'payload-key', 'file_id': 'f1'},
            'body': None},
    ),
    'email_finder_delete_file': (
        lambda c, w, f, s, out: c.email_finder_delete_file('f1'),
        {   'verb': 'GET',
            'url': 'bulkapi.zerobounce.net/email-finder/deletefile',
            'query': {'file_id': 'f1', 'api_key': 'payload-key'},
            'body': None},
    ),
    'send_domain_search_file': (
        lambda c, w, f, s, out: c.send_domain_search_file(f, 1, has_header_row=True),
        {   'verb': 'POST',
            'url': 'bulkapi.zerobounce.net/domain-search/sendfile',
            'query': {},
            'body': {   'domain_column': '1',
                        'has_header_row': 'true',
                        'api_key': 'payload-key',
                        'file': '<file emails.csv>'}},
    ),
    'send_domain_search_file_stream': (
        lambda c, w, f, s, out: c.send_domain_search_file_stream(s(), 'f.csv', 2),
        {   'verb': 'POST',
            'url': 'bulkapi.zerobounce.net/domain-search/sendfile',
            'query': {},
            'body': {   'domain_column': '2',
                        'has_header_row': 'false',
                        'api_key': 'payload-key',
                        'file': '<file f.csv>'}},
    ),
    'domain_search_file_status': (
        lambda c, w, f, s, out: c.domain_search_file_status('f1'),
        {   'verb': 'GET',
            'url': 'bulkapi.zerobounce.net/domain-search/filestatus',
            'query': {'file_id': 'f1', 'api_key': 'payload-key'},
            'body': None},
    ),
    'domain_search_get_file': (
        lambda c, w, f, s, out: c.domain_search_get_file('f1', out),
        {   'verb': 'GET',
            'url': 'bulkapi.zerobounce.net/domain-search/getfile',
            'query': {'api_key': 'payload-key', 'file_id': 'f1'},
            'body': None},
    ),
    'domain_search_delete_file': (
        lambda c, w, f, s, out: c.domain_search_delete_file('f1'),
        {   'verb': 'GET',
            'url': 'bulkapi.zerobounce.net/domain-search/deletefile',
            'query': {'file_id': 'f1', 'api_key': 'payload-key'},
            'body': None},
    ),
    'send_list_evaluator_file': (
        lambda c, w, f, s, out: c.send_list_evaluator_file(f, 3),
        {   'verb': 'POST',
            'url': 'bulkapi.zerobounce.net/v2/listevaluator/',
            'query': {},
            'body': {'api_key': 'payload-key', 'email_address_column': '3', 'file': '<file emails.csv>'}},
    ),
    'send_list_evaluator_file_stream': (
        lambda c, w, f, s, out: c.send_list_evaluator_file_stream(s(), 'f.csv', 2),
        {   'verb': 'POST',
            'url': 'bulkapi.zerobounce.net/v2/listevaluator/',
            'query': {},
            'body': {'api_key': 'payload-key', 'email_address_column': '2', 'file': '<file f.csv>'}},
    ),
    'get_list_evaluator_result': (
        lambda c, w, f, s, out: c.get_list_evaluator_result('f1'),
        {   'verb': 'GET',
            'url': 'bulkapi.zerobounce.net/v2/listevaluator/f1/',
            'query': {'api_key': 'payload-key'},
            'body': None},
    ),
    'send_evaluated_file': (
        lambda c, w, f, s, out: c.send_evaluated_file('f1'),
        {   'verb': 'POST',
            'url': 'bulkapi.zerobounce.net/v2/send-evaluated-file/',
            'query': {},
            'body': {'file_id': 'f1', 'api_key': 'payload-key'}},
    ),
    'add_filter': (
        lambda c, w, f, s, out: c.add_filter('allow', 'domain', 'example.com'),
        {   'verb': 'POST',
            'url': 'api.zerobounce.net/v2/filters/add',
            'query': {},
            'body': {'api_key': 'payload-key', 'rule': 'allow', 'target': 'domain', 'value': 'example.com'}},
    ),
    'list_filters': (
        lambda c, w, f, s, out: c.list_filters(),
        {   'verb': 'GET',
            'url': 'api.zerobounce.net/v2/filters/list',
            'query': {'api_key': 'payload-key'},
            'body': None},
    ),
    'list_filters use_post': (
        lambda c, w, f, s, out: c.list_filters(use_post=True),
        {   'verb': 'POST',
            'url': 'api.zerobounce.net/v2/filters/list',
            'query': {},
            'body': {'api_key': 'payload-key'}},
    ),
    'delete_filter': (
        lambda c, w, f, s, out: c.delete_filter('block', 'email', 'a@example.com'),
        {   'verb': 'POST',
            'url': 'api.zerobounce.net/v2/filters/delete',
            'query': {},
            'body': {   'api_key': 'payload-key',
                        'rule': 'block',
                        'target': 'email',
                        'value': 'a@example.com'}},
    ),
    'list_s3files': (
        lambda c, w, f, s, out: c.list_s3files(bucket='bkt', search='abc'),
        {   'verb': 'GET',
            'url': 'bulkapi.zerobounce.net/listS3files',
            'query': {'bucket': 'bkt', 'search': 'abc', 'api_key': 'payload-key'},
            'body': None},
    ),
    'validate_s3file': (
        lambda c, w, f, s, out: c.validate_s3file('f.csv', True, remove_duplicates=False, return_url=D),
        {   'verb': 'POST',
            'url': 'bulkapi.zerobounce.net/validateS3file',
            'query': {},
            'body': {   'has_header_row': 'true',
                        'file_name': 'f.csv',
                        'remove_duplicates': 'false',
                        'return_url': 'https://example.com/d',
                        'api_key': 'payload-key'}},
    ),
    'score_s3file': (
        lambda c, w, f, s, out: c.score_s3file('f.csv', False, return_url=D),
        {   'verb': 'POST',
            'url': 'bulkapi.zerobounce.net/scoreS3file',
            'query': {},
            'body': {   'has_header_row': 'false',
                        'file_name': 'f.csv',
                        'return_url': 'https://example.com/d',
                        'api_key': 'payload-key'}},
    ),
    'export_s3file': (
        lambda c, w, f, s, out: c.export_s3file('f1', export_bucket='out-bucket'),
        {   'verb': 'POST',
            'url': 'bulkapi.zerobounce.net/exportS3file',
            'query': {},
            'body': {'file_id': 'f1', 'export_bucket': 'out-bucket', 'api_key': 'payload-key'}},
    ),
    'email_finder_s3file': (
        lambda c, w, f, s, out: c.email_finder_s3file('f.csv', True, return_url=D),
        {   'verb': 'POST',
            'url': 'bulkapi.zerobounce.net/emailFinderS3file',
            'query': {},
            'body': {   'has_header_row': 'true',
                        'file_name': 'f.csv',
                        'return_url': 'https://example.com/d',
                        'api_key': 'payload-key'}},
    ),
    'domain_search_s3file': (
        lambda c, w, f, s, out: c.domain_search_s3file('f.csv', False, return_url=D),
        {   'verb': 'POST',
            'url': 'bulkapi.zerobounce.net/domainSearchS3file',
            'query': {},
            'body': {   'has_header_row': 'false',
                        'file_name': 'f.csv',
                        'return_url': 'https://example.com/d',
                        'api_key': 'payload-key'}},
    ),
    'validate_sftpfile': (
        lambda c, w, f, s, out: c.validate_sftpfile('f.csv', True, return_url=D),
        {   'verb': 'POST',
            'url': 'bulkapi.zerobounce.net/validateSFTPfile',
            'query': {},
            'body': {   'has_header_row': 'true',
                        'file_name': 'f.csv',
                        'return_url': 'https://example.com/d',
                        'api_key': 'payload-key'}},
    ),
    'score_sftpfile': (
        lambda c, w, f, s, out: c.score_sftpfile('f.csv', True, return_url=D),
        {   'verb': 'POST',
            'url': 'bulkapi.zerobounce.net/scoreSFTPfile',
            'query': {},
            'body': {   'has_header_row': 'true',
                        'file_name': 'f.csv',
                        'return_url': 'https://example.com/d',
                        'api_key': 'payload-key'}},
    ),
    'email_finder_sftpfile': (
        lambda c, w, f, s, out: c.email_finder_sftpfile('f.csv', True, return_url=D),
        {   'verb': 'POST',
            'url': 'bulkapi.zerobounce.net/emailFinderSFTPfile',
            'query': {},
            'body': {   'has_header_row': 'true',
                        'file_name': 'f.csv',
                        'return_url': 'https://example.com/d',
                        'api_key': 'payload-key'}},
    ),
    'domain_search_sftpfile': (
        lambda c, w, f, s, out: c.domain_search_sftpfile('f.csv', True, return_url=D),
        {   'verb': 'POST',
            'url': 'bulkapi.zerobounce.net/domainSearchSFTPfile',
            'query': {},
            'body': {   'has_header_row': 'true',
                        'file_name': 'f.csv',
                        'return_url': 'https://example.com/d',
                        'api_key': 'payload-key'}},
    ),
    'export_sftpfile': (
        lambda c, w, f, s, out: c.export_sftpfile('f1', export_path='/out'),
        {   'verb': 'POST',
            'url': 'bulkapi.zerobounce.net/exportSFTPfile',
            'query': {},
            'body': {'file_id': 'f1', 'export_path': '/out', 'api_key': 'payload-key'}},
    ),
    'get_inbox_placement_providers': (
        lambda c, w, f, s, out: c.get_inbox_placement_providers(),
        {'verb': 'GET', 'url': 'bulkapi.zerobounce.net/api/ipt/providers', 'query': {}, 'body': None},
    ),
    'get_inbox_placement_test_types': (
        lambda c, w, f, s, out: c.get_inbox_placement_test_types(),
        {'verb': 'GET', 'url': 'bulkapi.zerobounce.net/api/ipt/test-types', 'query': {}, 'body': None},
    ),
    'create_inbox_placement_test': (
        lambda c, w, f, s, out: c.create_inbox_placement_test('Test', test_type=1, sender_email='s@example.com', provider_ids=[1, 2], seed_ids=[3], providers=[{'id': 1, 'maxSeeds': 2}], webhook_url='https://example.com/h'),
        {   'verb': 'POST',
            'url': 'bulkapi.zerobounce.net/api/ipt/test',
            'query': {},
            'body': {   'name': 'Test',
                        'testType': 1,
                        'senderEmail': 's@example.com',
                        'providerIds': [1, 2],
                        'seedIds': [3],
                        'providers': [{'id': 1, 'maxSeeds': 2}],
                        'webhookUrl': 'https://example.com/h'}},
    ),
    'get_inbox_placement_test': (
        lambda c, w, f, s, out: c.get_inbox_placement_test(7),
        {'verb': 'GET', 'url': 'bulkapi.zerobounce.net/api/ipt/test/7', 'query': {}, 'body': None},
    ),
    'list_inbox_placement_tests': (
        lambda c, w, f, s, out: c.list_inbox_placement_tests(status='finished', created_after='2026-01-01', created_before='2026-02-01', page=2, page_size=10),
        {   'verb': 'GET',
            'url': 'bulkapi.zerobounce.net/api/ipt/tests',
            'query': {   'status': 'finished',
                         'createdAfter': '2026-01-01',
                         'createdBefore': '2026-02-01',
                         'page': '2',
                         'page_size': '10'},
            'body': None},
    ),
    'delete_inbox_placement_test': (
        lambda c, w, f, s, out: c.delete_inbox_placement_test(7),
        {'verb': 'DELETE', 'url': 'bulkapi.zerobounce.net/api/ipt/test/7', 'query': {}, 'body': None},
    ),
    'get_inbox_placement_webhook': (
        lambda c, w, f, s, out: c.get_inbox_placement_webhook(),
        {'verb': 'GET', 'url': 'bulkapi.zerobounce.net/api/ipt/webhook', 'query': {}, 'body': None},
    ),
    'set_inbox_placement_webhook': (
        lambda c, w, f, s, out: c.set_inbox_placement_webhook('https://example.com/hook'),
        {   'verb': 'PUT',
            'url': 'bulkapi.zerobounce.net/api/ipt/webhook',
            'query': {},
            'body': {'webhookUrl': 'https://example.com/hook'}},
    ),
    'guess_format': (
        lambda c, w, f, s, out: c.guess_format('example.com', first_name='Ann', middle_name='B', last_name='Lee'),
        {   'verb': 'GET',
            'url': 'api.zerobounce.net/v2/guessformat',
            'query': {   'domain': 'example.com',
                         'first_name': 'Ann',
                         'middle_name': 'B',
                         'last_name': 'Lee',
                         'api_key': 'payload-key'},
            'body': None},
    ),
    'find_email_format': (
        lambda c, w, f, s, out: c.find_email_format(first_name='Ann', domain='example.com', middle_name='B', last_name='Lee'),
        {   'verb': 'GET',
            'url': 'api.zerobounce.net/v2/guessformat',
            'query': {   'first_name': 'Ann',
                         'domain': 'example.com',
                         'middle_name': 'B',
                         'last_name': 'Lee',
                         'api_key': 'payload-key'},
            'body': None},
    ),
    'find_email_format use_post': (
        lambda c, w, f, s, out: c.find_email_format(first_name='Ann', company_name='Acme', use_post=True),
        {   'verb': 'POST',
            'url': 'api.zerobounce.net/v2/guessformat',
            'query': {},
            'body': {'first_name': 'Ann', 'company_name': 'Acme', 'api_key': 'payload-key'}},
    ),
    'find_domain': (
        lambda c, w, f, s, out: c.find_domain(domain='example.com'),
        {   'verb': 'GET',
            'url': 'api.zerobounce.net/v2/guessformat',
            'query': {'domain': 'example.com', 'api_key': 'payload-key'},
            'body': None},
    ),
    'find_domain use_post': (
        lambda c, w, f, s, out: c.find_domain(company_name='Acme', use_post=True),
        {   'verb': 'POST',
            'url': 'api.zerobounce.net/v2/guessformat',
            'query': {},
            'body': {'company_name': 'Acme', 'api_key': 'payload-key'}},
    ),
}

WARMUP = {
    'list_sending_accounts': (
        lambda c, w, f, s, out: w.list_sending_accounts(),
        {   'verb': 'GET',
            'url': 'warmup-api.zerobounce.net/api/v1/warmup/sending-accounts',
            'query': {},
            'body': None},
    ),
    'get_sending_account': (
        lambda c, w, f, s, out: w.get_sending_account('a@example.com'),
        {   'verb': 'GET',
            'url': 'warmup-api.zerobounce.net/api/v1/warmup/sending-account',
            'query': {'from_address': 'a@example.com'},
            'body': None},
    ),
    'add_sending_account': (
        lambda c, w, f, s, out: w.add_sending_account('a@example.com', 'self_managed', engagement_rule_id=0, ignore_conflict=True),
        {   'verb': 'POST',
            'url': 'warmup-api.zerobounce.net/api/v1/warmup/sending-accounts',
            'query': {},
            'body': {   'from_address': 'a@example.com',
                        'onboarding_model': 'self_managed',
                        'engagement_rule_id': 0,
                        'ignore_conflict': True}},
    ),
    'add_sending_account zb_managed': (
        lambda c, w, f, s, out: w.add_sending_account('a@example.com', 'zb_managed', email_content={'company_name': 'Acme', 'company_website': 'https://acme.example', 'company_description': 'Tools', 'types_of_emails': ['newsletter'], 'example_email': 'Hi'}, managed_sending={'weekdays_only': True, 'timezone': 'Asia/Kolkata', 'timezone_offset': 5.5, 'warmup_start_date': '2026-11-02'}),
        {   'verb': 'POST',
            'url': 'warmup-api.zerobounce.net/api/v1/warmup/sending-accounts',
            'query': {},
            'body': {   'from_address': 'a@example.com',
                        'onboarding_model': 'zb_managed',
                        'email_content': {   'company_name': 'Acme',
                                             'company_website': 'https://acme.example',
                                             'company_description': 'Tools',
                                             'types_of_emails': ['newsletter'],
                                             'example_email': 'Hi'},
                        'managed_sending': {   'weekdays_only': True,
                                               'timezone': 'Asia/Kolkata',
                                               'timezone_offset': 5.5,
                                               'warmup_start_date': '2026-11-02'}}},
    ),
    'update_sending_account': (
        lambda c, w, f, s, out: w.update_sending_account('a@example.com', 1, 4, True),
        {   'verb': 'PUT',
            'url': 'warmup-api.zerobounce.net/api/v1/warmup/sending-accounts',
            'query': {},
            'body': {   'team_id': 1,
                        'from_address': 'a@example.com',
                        'engagement_rule_id': 1,
                        'status_id': 4,
                        'auto_enable': True}},
    ),
    'delete_sending_account': (
        lambda c, w, f, s, out: w.delete_sending_account('a@example.com'),
        {   'verb': 'DELETE',
            'url': 'warmup-api.zerobounce.net/api/v1/warmup/sending-accounts',
            'query': {'from_address': 'a@example.com'},
            'body': None},
    ),
    'change_from_address': (
        lambda c, w, f, s, out: w.change_from_address('a@example.com', 'b@example.com'),
        {   'verb': 'PUT',
            'url': 'warmup-api.zerobounce.net/api/v1/warmup/smtp-credentials',
            'query': {},
            'body': {   'team_id': 1,
                        'old_from_address': 'a@example.com',
                        'new_from_address': 'b@example.com'}},
    ),
    'list_from_addresses': (
        lambda c, w, f, s, out: w.list_from_addresses(search_from='a', offset=5, limit=10),
        {   'verb': 'GET',
            'url': 'warmup-api.zerobounce.net/api/v1/warmup/from-addresses',
            'query': {'search_from': 'a', 'offset': '5', 'limit': '10'},
            'body': None},
    ),
    'get_engagement_rules': (
        lambda c, w, f, s, out: w.get_engagement_rules(),
        {   'verb': 'GET',
            'url': 'warmup-api.zerobounce.net/api/v1/warmup/engagement-rules',
            'query': {},
            'body': None},
    ),
    'set_engagement_rule': (
        lambda c, w, f, s, out: w.set_engagement_rule('a@example.com', 2),
        {   'verb': 'PUT',
            'url': 'warmup-api.zerobounce.net/api/v1/warmup/engagement-rule',
            'query': {'c_from': 'a@example.com'},
            'body': {'rule_id': 2}},
    ),
    'get_custom_engagement': (
        lambda c, w, f, s, out: w.get_custom_engagement('a@example.com'),
        {   'verb': 'GET',
            'url': 'warmup-api.zerobounce.net/api/v1/warmup/custom-engagement/a%40example.com',
            'query': {},
            'body': None},
    ),
    'create_custom_engagement': (
        lambda c, w, f, s, out: w.create_custom_engagement('a@example.com', 10, 20, 5),
        {   'verb': 'POST',
            'url': 'warmup-api.zerobounce.net/api/v1/warmup/custom-engagement',
            'query': {},
            'body': {'c_from': 'a@example.com', 'reply_pct': 10, 'important_pct': 20, 'click_pct': 5}},
    ),
    'update_custom_engagement': (
        lambda c, w, f, s, out: w.update_custom_engagement('a@example.com', 11, 21, 6),
        {   'verb': 'PUT',
            'url': 'warmup-api.zerobounce.net/api/v1/warmup/custom-engagement',
            'query': {},
            'body': {'c_from': 'a@example.com', 'reply_pct': 11, 'important_pct': 21, 'click_pct': 6}},
    ),
    'delete_custom_engagement': (
        lambda c, w, f, s, out: w.delete_custom_engagement('a@example.com', 1),
        {   'verb': 'DELETE',
            'url': 'warmup-api.zerobounce.net/api/v1/warmup/custom-engagement',
            'query': {},
            'body': {'c_from': 'a@example.com', 'engagement_rule_id': 1}},
    ),
    'get_seeds': (
        lambda c, w, f, s, out: w.get_seeds(),
        {'verb': 'GET', 'url': 'warmup-api.zerobounce.net/api/v1/warmup/seeds', 'query': {}, 'body': None},
    ),
    'download_seeds': (
        lambda c, w, f, s, out: w.download_seeds(),
        {   'verb': 'GET',
            'url': 'warmup-api.zerobounce.net/api/v1/warmup/seeds/download',
            'query': {},
            'body': None},
    ),
    'get_seed_count': (
        lambda c, w, f, s, out: w.get_seed_count(),
        {   'verb': 'GET',
            'url': 'warmup-api.zerobounce.net/api/v1/warmup/seed-count',
            'query': {},
            'body': None},
    ),
    'get_progress_today': (
        lambda c, w, f, s, out: w.get_progress_today(),
        {   'verb': 'GET',
            'url': 'warmup-api.zerobounce.net/api/v1/warmup/progress-today',
            'query': {},
            'body': None},
    ),
    'get_sent_today': (
        lambda c, w, f, s, out: w.get_sent_today(),
        {   'verb': 'GET',
            'url': 'warmup-api.zerobounce.net/api/v1/warmup/sent-today',
            'query': {},
            'body': None},
    ),
    'get_emails_per_day': (
        lambda c, w, f, s, out: w.get_emails_per_day(),
        {   'verb': 'GET',
            'url': 'warmup-api.zerobounce.net/api/v1/warmup/emails-per-day',
            'query': {},
            'body': None},
    ),
    'get_statistics': (
        lambda c, w, f, s, out: w.get_statistics('a@example.com'),
        {   'verb': 'GET',
            'url': 'warmup-api.zerobounce.net/api/v1/warmup/statistics',
            'query': {'from_address': 'a@example.com'},
            'body': None},
    ),
    'get_statistics_per_day': (
        lambda c, w, f, s, out: w.get_statistics_per_day('a@example.com', '2026-09-01', '2026-09-14'),
        {   'verb': 'GET',
            'url': 'warmup-api.zerobounce.net/api/v1/warmup/statistics-per-day',
            'query': {   'from_address': 'a@example.com',
                         'start_date': '2026-09-01',
                         'end_date': '2026-09-14'},
            'body': None},
    ),
    'get_statistics_detailed': (
        lambda c, w, f, s, out: w.get_statistics_detailed('a@example.com'),
        {   'verb': 'GET',
            'url': 'warmup-api.zerobounce.net/api/v1/warmup/statistics-detailed',
            'query': {'c_from': 'a@example.com'},
            'body': None},
    ),
    'download_statistics': (
        lambda c, w, f, s, out: w.download_statistics('a@example.com'),
        {   'verb': 'GET',
            'url': 'warmup-api.zerobounce.net/api/v1/warmup/statistics/download',
            'query': {'c_from': 'a@example.com'},
            'body': None},
    ),
    'get_from_address_statistics': (
        lambda c, w, f, s, out: w.get_from_address_statistics('a@example.com'),
        {   'verb': 'GET',
            'url': 'warmup-api.zerobounce.net/api/v1/warmup/from-address-statistics',
            'query': {'from_address': 'a@example.com'},
            'body': None},
    ),
    'check_domain_dmarc': (
        lambda c, w, f, s, out: w.check_domain_dmarc('a@example.com', dkim_selector='sel'),
        {   'verb': 'GET',
            'url': 'warmup-api.zerobounce.net/api/v1/warmup/check-domain-dmarc',
            'query': {'from_address': 'a@example.com', 'dkim_selector': 'sel'},
            'body': None},
    ),
    'test_smtp_configuration': (
        lambda c, w, f, s, out: w.test_smtp_configuration('a@example.com', 'user', 'pass', 'smtp.example.com', 587),
        {   'verb': 'POST',
            'url': 'warmup-api.zerobounce.net/api/v1/warmup/test-smtp-configuration',
            'query': {},
            'body': {   'from_address': 'a@example.com',
                        'username': 'user',
                        'password': 'pass',
                        'server': 'smtp.example.com',
                        'port': 587}},
    ),
}


def _shape(request):
    body = request.json if request.json is not None else (dict(request.form) if request.form or request.files else None)
    if request.files:
        body = dict(body or {})
        for name, upload in request.files.items():
            body[name] = "<file %s>" % upload["filename"]
    return {"verb": request.method, "url": f"{request.host}{request.path}", "query": request.query, "body": body}


def _public(cls):
    return {name for name in dir(cls) if not name.startswith("_") and callable(getattr(cls, name))}


class RequestPayloadTest(TestCase):
    def setUp(self):
        self.sent = []

        def send(session, request, **kwargs):
            self.sent.append(RecordedRequest(request.method, request.url, request.body, request.headers))
            return _response(200, b'{"success": true}', "application/json")

        patcher = patch("requests.sessions.Session.send", send)
        patcher.start()
        self.addCleanup(patcher.stop)
        folder = tempfile.mkdtemp()
        self.csv = os.path.join(folder, "emails.csv")
        with open(self.csv, "w") as handle:
            handle.write("email\na@example.com\n")
        self.out = os.path.join(folder, "out.csv")

    def _check(self, name, call, expected):
        self.sent.clear()
        client = ZeroBounce("payload-key")
        warmup = ZeroBounceWarmup("warmup-key")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # guess_format is deprecated
            try:
                call(client, warmup, self.csv, lambda: io.BytesIO(b"email\na@example.com\n"), self.out)
            except Exception:  # noqa: BLE001 - the canned answer does not fit every call; only the request matters
                pass
        self.assertEqual([_shape(request) for request in self.sent], [expected], name)

    def test_the_tables_cover_every_public_request_method(self):
        self.assertEqual(_public(ZeroBounce) - NOT_REQUESTS - {n.split()[0] for n in CORE}, set())
        self.assertEqual(_public(ZeroBounceWarmup) - {n.split()[0] for n in WARMUP}, set())

    def test_every_client_request(self):
        for name, (call, expected) in CORE.items():
            with self.subTest(name):
                self._check(name, call, expected)

    def test_every_warmup_request(self):
        for name, (call, expected) in WARMUP.items():
            with self.subTest(name):
                self._check(name, call, expected)
