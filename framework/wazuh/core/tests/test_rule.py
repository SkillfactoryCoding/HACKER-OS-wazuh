#!/usr/bin/env python
# Copyright (C) 2015-2019, Wazuh Inc.
# Created by Wazuh, Inc. <info@wazuh.com>.
# This program is free software; you can redistribute it and/or modify it under the terms of GPLv2

import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), '..', '..', '..', '..', 'api'))

with patch('wazuh.common.ossec_uid'):
    with patch('wazuh.common.ossec_gid'):
        sys.modules['wazuh.rbac.orm'] = MagicMock()
        sys.modules['api'] = MagicMock()
        import wazuh.rbac.decorators

        del sys.modules['wazuh.rbac.orm']
        del sys.modules['api']
        from wazuh.tests.util import RBAC_bypasser

        wazuh.rbac.decorators.expose_resources = RBAC_bypasser
        from wazuh.exception import WazuhError
        from wazuh.core import rule

# variables
ruleset_conf = {
    'decoder_dir': ['ruleset/decoders', 'etc/decoders'],
    'rule_dir': ['ruleset/rules', 'etc/rules'], 'rule_exclude': ['0215-policy_rules.xml'],
    'list': ['etc/lists/audit-keys', 'etc/lists/amazon/aws-eventnames', 'etc/lists/security-eventchannel']
}
files = [
    '0425-cisco-estreamer_rules.xml'
]


@pytest.mark.parametrize('detail, value, details', [
    ('new', '4', {'actual': '3'}),
    ('actual', '4', {'actual': '3'}),
])
def test_add_detail(detail, value, details):
    """Test add_detail rule core function."""
    rule.add_detail(detail, value, details)
    assert detail in details.keys()
    assert value in details[detail]


@pytest.mark.parametrize('src_list, element', [
    (['wazuh', 'ossec'], 'rbac'),
    (['wazuh', 'ossec', 'rbac'], ['new']),
])
def test_add_unique_element(src_list, element):
    """Test add_unique_element rule core function."""
    rule.add_unique_element(src_list, element)
    if isinstance(element, list):
        for e in element:
            assert e in src_list
    else:
        assert element in src_list


@pytest.mark.parametrize('status, expected_result', [
    ('enabled', 'enabled'),
    ('disabled', 'disabled'),
    ('all', 'all'),
    (rule.Status.S_ALL.value, 'all'),
    (None, 'all'),
    ('unexistent', WazuhError(1202))
])
def test_check_status(status, expected_result):
    """Test check_status rule core function."""
    try:
        result = rule.check_status(status)
        assert result == expected_result
    except WazuhError as e:
        assert e.code == expected_result.code


@pytest.mark.parametrize('rule_file, rule_path, rule_status, exception', [
    ('0010-rules_config.xml', 'tests/data/rules', 'enabled', None),
    ('0015-ossec_rules.xml', 'tests/data/rules', 'enabled', None),
    ('0260-nginx_rules.xml', 'tests/data/rules', 'enabled', None),
    ('0350-amazon_rules.xml', 'tests/data/rules', 'enabled', None),
    ('noexists.xml', 'tests/data/rules', 'enabled', WazuhError(1201)),
    ('no_permissions.xml', 'tests/data/rules', 'enabled', WazuhError(1207))
])
@patch("wazuh.common.ossec_path", new=os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
@patch("wazuh.common.ruleset_rules_path", new='core/tests/data/rules')
def test_load_rules_from_file(rule_file, rule_path, rule_status, exception):
    """Test set_groups rule core function."""
    try:
        result = rule.load_rules_from_file(rule_file, rule_path, rule_status)
        for r in result:
            assert r['file'] == rule_file
            assert r['path'] == rule_path
            assert r['status'] == rule_status
    except WazuhError as e:
        assert e.code == exception.code


@pytest.mark.parametrize('tmp_data, parameters, expected_result', [
    ([
         {'file': 'one.xml', 'status': 'all'},
         {'file': 'two.xml', 'status': 'disabled'},
         {'file': 'three.xml', 'status': None},
         {'file': 'four.xml', 'status': 'enabled'}
     ],
     {'status': 'disabled'},
     [
         {'file': 'two.xml', 'status': 'disabled'},
     ]),
    ([
         {'file': 'one.xml', 'exists': False},
         {'file': 'two.xml', 'exists': 'true'},
         {'file': 'three.xml', 'exists': True},
         {'file': 'four.xml', 'exists': 'false'}
     ],
     {'exists': 'true'},
     [
         {'file': 'two.xml', 'exists': 'true'},
     ])
])
def test_remove_files(tmp_data, parameters, expected_result):
    """Test set_groups rule core function."""
    result = rule._remove_files(tmp_data, parameters)
    assert result == expected_result


def test_format_rule_decoder_file():
    """Test format_rule_decoder_file rule core function."""
    for file in files:
        result = rule.format_rule_decoder_file(
            ruleset_conf, {'status': rule.Status.S_ENABLED.value, 'path': 'ruleset/rules', 'file': file},
            ['rule_include', 'rule_exclude', 'rule_dir'])
        print(result)
        assert result == [{'file': file, 'path': 'ruleset/rules', 'status': 'enabled'}]
