# Copyright (C) 2015, Wazuh Inc.
# Created by Wazuh, Inc. <info@wazuh.com>.
# This program is free software; you can redistribute it and/or modify it
# under the terms of GPLv2
import io
import os
import sys
import zipfile
import zlib
from datetime import datetime
from time import time
from unittest.mock import MagicMock, mock_open, patch, call, ANY

import pytest
from wazuh.core import common
from wazuh.core.utils import get_date_from_timestamp

with patch('wazuh.common.wazuh_uid'):
    with patch('wazuh.common.wazuh_gid'):
        sys.modules['wazuh.rbac.orm'] = MagicMock()
        import wazuh.rbac.decorators

        del sys.modules['wazuh.rbac.orm']

        from wazuh.tests.util import RBAC_bypasser

        wazuh.rbac.decorators.expose_resources = RBAC_bypasser
        import wazuh.core.cluster.cluster as cluster
        from wazuh import WazuhException
        from wazuh.core.exception import WazuhError, WazuhInternalError

agent_groups = b"default,windows-servers"

# Valid configurations
default_cluster_configuration = {
    'cluster': {
        'disabled': 'yes',
        'node_type': 'master',
        'name': 'wazuh',
        'node_name': 'node01',
        'key': '',
        'port': 1516,
        'bind_addr': '0.0.0.0',
        'nodes': ['NODE_IP'],
        'hidden': 'no'
    }
}

custom_cluster_configuration = {
    'cluster': {
        'disabled': 'no',
        'node_type': 'master',
        'name': 'wazuh',
        'node_name': 'node01',
        'key': 'a' * 32,
        'port': 1516,
        'bind_addr': '0.0.0.0',
        'nodes': ['172.10.0.100'],
        'hidden': False
    }
}

custom_incomplete_configuration = {
    'cluster': {
        'key': 'a' * 32,
        'node_name': 'master'
    }
}


@pytest.mark.parametrize('read_config, message', [
    ({'cluster': {'key': ''}}, "Unspecified key"),
    ({'cluster': {'key': 'a' * 15}}, "Key must be"),
    ({'cluster': {'node_type': 'random', 'key': 'a' * 32}}, "Invalid node type"),
    ({'cluster': {'port': 'string', 'node_type': 'master'}}, "Port has to"),
    ({'cluster': {'port': 90}}, "Port must be"),
    ({'cluster': {'port': 70000}}, "Port must be"),
    ({'cluster': {'port': 1516, 'nodes': ['NODE_IP'], 'key': 'a' * 32, 'node_type': 'master'}}, "Invalid elements"),
    ({'cluster': {'nodes': ['localhost'], 'key': 'a' * 32, 'node_type': 'master'}}, "Invalid elements"),
    ({'cluster': {'nodes': ['0.0.0.0'], 'key': 'a' * 32, 'node_type': 'master'}}, "Invalid elements"),
    ({'cluster': {'nodes': ['127.0.1.1'], 'key': 'a' * 32, 'node_type': 'master'}}, "Invalid elements"),
    ({'cluster': {'nodes': ['127.0.1.1', '127.0.1.2'], 'key': 'a' * 32, 'node_type': 'master'}}, "Invalid elements"),
])
def test_check_cluster_config_ko(read_config, message):
    """Check wrong configurations to check the proper exceptions are raised."""
    with patch('wazuh.core.cluster.utils.get_ossec_conf', return_value=read_config) as m:
        with pytest.raises(WazuhException, match=rf'.* 3004 .* {message}'):
            configuration = wazuh.core.cluster.utils.read_config()

            for key in m.return_value["cluster"]:
                if key in configuration:
                    configuration[key] = m.return_value["cluster"][key]

            cluster.check_cluster_config(configuration)


def test_get_node():
    """Check the correct output of the get_node function."""
    test_dict = {"node_name": "master", "name": "master",
                 "node_type": "master"}

    with patch('wazuh.core.cluster.cluster.read_config', return_value=test_dict):
        get_node = cluster.get_node()
        assert isinstance(get_node, dict)
        assert get_node["node"] == test_dict["node_name"]
        assert get_node["cluster"] == test_dict["name"]
        assert get_node["type"] == test_dict["node_type"]


def test_check_cluster_status():
    """Check the correct output of the check_cluster_status function."""
    assert isinstance(cluster.check_cluster_status(), bool)


@patch('os.path.getmtime', return_value=45)
@patch('wazuh.core.cluster.cluster.md5', return_value="hash")
@patch("wazuh.core.cluster.cluster.path.join", return_value="/mock/foo/bar")
@patch('wazuh.core.cluster.cluster.walk', return_value=[('/foo/bar', (), ('spam', 'eggs', '.merged'))])
def test_walk_dir(walk_mock, path_join_mock, md5_mock, getmtime_mock):
    """Check the different outputs of the walk_files function."""

    all_mocks = [walk_mock, path_join_mock, md5_mock, getmtime_mock]

    def reset_mocks(mocks):
        """Auxiliary function to reset the necessary mocks."""
        for mock in mocks:
            mock.reset_mock()

    # Check the first if and nested else
    assert cluster.walk_dir(dirname="/foo/bar", recursive=False, files=['all'], excluded_files=['ar.conf'],
                            excluded_extensions=[".xml", ".txt"], get_cluster_item_key="") == {}
    walk_mock.assert_called_once_with(path_join_mock.return_value, topdown=True)
    path_join_mock.assert_called_once_with(common.WAZUH_PATH, '/foo/bar')
    md5_mock.assert_not_called()
    getmtime_mock.assert_not_called()

    reset_mocks(all_mocks)

    # Check nested if
    assert cluster.walk_dir(dirname="/foo/bar", recursive=True, files=['all'], excluded_files=['ar.conf', 'spam'],
                            excluded_extensions=[".xml", ".txt"], get_cluster_item_key="",
                            previous_status={path_join_mock.return_value: {'mod_time': 45}}) == {
               path_join_mock.return_value: {'mod_time': 45}}

    walk_mock.assert_called_once_with(path_join_mock.return_value, topdown=True)
    path_join_mock.assert_has_calls([call(common.WAZUH_PATH, '/foo/bar'),
                                     call('/mock/foo/bar', 'eggs'), call('/foo/bar', 'eggs'),
                                     call('/mock/foo/bar', '.merged'),
                                     call('/foo/bar', '.merged')], any_order=True)
    md5_mock.assert_not_called()
    getmtime_mock.assert_has_calls([call(path_join_mock.return_value), call(path_join_mock.return_value)])

    reset_mocks(all_mocks)

    assert cluster.walk_dir(dirname="/foo/bar", recursive=True, files=['all'], excluded_files=['ar.conf', 'spam'],
                            excluded_extensions=[".xml", ".txt"], get_cluster_item_key="",
                            previous_status={path_join_mock.return_value: {'mod_time': 35}}) == {
               '/mock/foo/bar': {'mod_time': 45, 'cluster_item_key': '', 'merged': True, 'merge_type': 'agent-groups',
                                 'merge_name': '/mock/foo/bar', 'md5': 'hash'}}

    walk_mock.assert_called_once_with(path_join_mock.return_value, topdown=True)
    path_join_mock.assert_has_calls([call(common.WAZUH_PATH, '/foo/bar'),
                                     call('/mock/foo/bar', 'eggs'), call('/foo/bar', 'eggs'),
                                     call('/mock/foo/bar', '.merged'),
                                     call('/foo/bar', '.merged')], any_order=True)
    md5_mock.assert_has_calls([call(path_join_mock.return_value), call(path_join_mock.return_value)])
    getmtime_mock.assert_has_calls([call(path_join_mock.return_value), call(path_join_mock.return_value)])

    reset_mocks(all_mocks)

    # Check the key error
    assert cluster.walk_dir(dirname="/foo/bar", recursive=True, files=['all'], excluded_files=['ar.conf', 'spam'],
                            excluded_extensions=[".xml", ".txt"], get_cluster_item_key="",
                            previous_status={path_join_mock.return_value: {'mod_mock_time': 35}}) == {
               '/mock/foo/bar': {'mod_time': 45, 'cluster_item_key': '', 'merged': True, 'merge_type': 'agent-groups',
                                 'merge_name': '/mock/foo/bar', 'md5': 'hash'}}

    walk_mock.assert_called_once_with(path_join_mock.return_value, topdown=True)
    path_join_mock.assert_has_calls([call(common.WAZUH_PATH, '/foo/bar'),
                                     call('/mock/foo/bar', 'eggs'), call('/foo/bar', 'eggs'),
                                     call('/mock/foo/bar', '.merged'),
                                     call('/foo/bar', '.merged')], any_order=True)
    md5_mock.assert_has_calls([call(path_join_mock.return_value), call(path_join_mock.return_value)])
    getmtime_mock.assert_has_calls([call(path_join_mock.return_value), call(path_join_mock.return_value)])


@patch('wazuh.core.cluster.cluster.walk', return_value=[('/foo/bar', (), ['spam'])])
@patch('os.path.join', return_value='/foo/bar')
def test_walk_dir_ko(mock_path_join, mock_walk):
    """Check all errors that can be raised by the function walk_dir."""
    with patch.object(wazuh.core.cluster.cluster.logger, "debug") as mock_logger:
        with patch('os.path.getmtime', side_effect=FileNotFoundError):
            cluster.walk_dir("/foo/bar", True, ["all"], ["ar.conf"], [".xml", ".txt"], "",
                             {'/foo/bar/': {'mod_time': True}})
            mock_logger.assert_called_with("File spam was deleted in previous iteration: ")

    with patch.object(wazuh.core.cluster.cluster.logger, "error") as mock_logger:
        with patch('os.path.getmtime', side_effect=PermissionError):
            cluster.walk_dir("/foo/bar", True, ["all"], ["ar.conf"], [".xml", ".txt"], "",
                             {'/foo/bar/': {'mod_time': True}})
            mock_logger.assert_called_with("Can't read metadata from file spam: ")

    with patch('wazuh.core.cluster.cluster.walk', side_effect=OSError):
        with pytest.raises(WazuhInternalError, match=r'.* 3015 .*'):
            cluster.walk_dir("/foo/bar", True, ["all"], ["ar.conf"], [".xml", ".txt"], "",
                             {'/foo/bar/': {'mod_time': True}})

    with patch('os.path.getmtime', return_value=35):
        cluster.walk_dir("/foo/bar", True, ["all"], ["ar.conf"], [".xml", ".txt"], "",
                         {'/foo/bar/': {'mod_time': False}})


@patch('wazuh.core.cluster.cluster.get_cluster_items', return_value={
    "files": {
        "etc/": {
            "permissions": 416,
            "source": "master",
            "files": [
                "client.keys"
            ],
            "recursive": False,
            "restart": False,
            "remove_subdirs_if_empty": False,
            "extra_valid": False,
            "description": "client keys file database"
        },
        "excluded_files": [
            "ar.conf",
            "ossec.conf"
        ],
        "excluded_extensions": [
            "~",
            ".tmp",
            ".lock",
            ".swp"
        ]
    }
})
def test_get_files_status(mock_get_cluster_items):
    """Check the different outputs of the get_files_status function."""

    test_dict = {"path": "metadata"}

    with patch('wazuh.core.cluster.cluster.walk_dir', return_value=test_dict):
        assert isinstance(cluster.get_files_status(), dict)
        assert cluster.get_files_status()["path"] == test_dict["path"]

    with patch('wazuh.core.cluster.cluster.walk_dir', side_effect=Exception):
        with patch.object(wazuh.core.cluster.cluster.logger, "warning") as logger_mock:
            cluster.get_files_status()
            logger_mock.assert_called_once_with(f"Error getting file status: .")


@pytest.mark.parametrize('failed_item, exists, expected_result', [
    ('/test_file0', False, {'missing': {'/test_file3': 'ok'}, 'shared': {'/test_file1': 'test'},
                            'extra': {'/test_file2': 'test'}}),
    ('/test_file1', False, {'missing': {'/test_file0': 'test', '/test_file3': 'ok'}, 'shared': {},
                             'extra': {'/test_file1': 'test', '/test_file2': 'test'}}),
    ('/test_file2', False, {'missing': {'/test_file0': 'test', '/test_file3': 'ok'}, 'shared': {'/test_file1': 'test'},
                             'extra': {'/test_file2': 'test'}}),
    ('/test_file0', True, {'missing': {'/test_file3': 'ok'}, 'shared': {'/test_file1': 'test'},
                           'extra': {'/test_file2': 'test'}}),
    ('/test_file1', True, {'missing': {'/test_file0': 'test', '/test_file3': 'ok'}, 'shared': {},
                            'extra': {'/test_file2': 'test'}}),
    ('/test_file2', True, {'missing': {'/test_file0': 'test', '/test_file3': 'ok'}, 'shared': {'/test_file1': 'test'},
                            'extra': {'/test_file2': 'test'}}),
])
def test_update_cluster_control(failed_item, exists, expected_result):
    """Check if cluster_control json is updated as expected."""
    ko_files = {
        'missing': {'/test_file0': 'test',
                    '/test_file3': 'ok'},
        'shared': {'/test_file1': 'test'},
        'extra': {'/test_file2': 'test'}
    }
    cluster.update_cluster_control(failed_item, ko_files, exists=exists)
    assert ko_files == expected_result



@patch('zlib.compress', return_value=b'compressed_test_content')
@patch('wazuh.core.cluster.cluster.get_cluster_items')
@patch('wazuh.core.cluster.cluster.mkdir_with_mode')
@patch('wazuh.core.cluster.cluster.path.dirname', return_value='/some/path')
@patch('wazuh.core.cluster.cluster.path.exists', return_value=False)
def test_compress_files_ok(mock_path_exists, mock_path_dirname, mock_mkdir_with_mode, mock_get_cluster_items,
                           mock_zlib):
    """Check if the compressing function is working properly."""
    mock_get_cluster_items.return_value = {'intervals': {'communication': {'max_zip_size': 10000, 'compress_level': 0}}}

    with patch('builtins.open', mock_open(read_data='test_content')) as open_mock:
        assert isinstance(cluster.compress_files('some_name', ['some/path', 'another/path'], {'ko_file': 'file'}), str)
        assert open_mock.call_args_list == [call(ANY, 'ab'), call(os.path.join(common.WAZUH_PATH, 'some/path'), 'rb'),
                                            call(os.path.join(common.WAZUH_PATH, 'another/path'), 'rb')]
        assert open_mock.return_value.write.call_args_list == [
            call(f'some/path{cluster.PATH_SEP}compressed_test_content{cluster.FILE_SEP}'.encode()),
            call(f'another/path{cluster.PATH_SEP}compressed_test_content{cluster.FILE_SEP}'.encode()),
            call(f'files_metadata.json{cluster.PATH_SEP}compressed_test_content'.encode())
        ]


@patch('wazuh.core.cluster.cluster.get_cluster_items')
@patch('wazuh.core.cluster.cluster.mkdir_with_mode')
@patch('wazuh.core.cluster.cluster.path.dirname', return_value='/some/path')
@patch('wazuh.core.cluster.cluster.path.exists', return_value=False)
def test_compress_files_ko(mock_path_exists, mock_path_dirname, mock_mkdir_with_mode, mock_get_cluster_items):
    """Check if the compressing function is raising every exception."""
    with patch('builtins.open', mock_open(read_data='test_content')):
        mock_get_cluster_items.return_value = {'intervals': {'communication': {'max_zip_size': 5,'compress_level': 0}}}
        with patch.object(wazuh.core.cluster.cluster.logger, 'warning') as warning_logger:
                cluster.compress_files('some_name', ['some/path'], {'missing': {}, 'shared': {}})
                warning_logger.assert_called_with(f'File too large to be synced: '
                                                  f'{os.path.join(common.WAZUH_PATH, "some/path")}')

        mock_get_cluster_items.return_value = {'intervals': {'communication': {'max_zip_size': 15, 'compress_level': 0}}
                                               }
        with patch('zlib.compress', side_effect=zlib.error):
            with pytest.raises(WazuhError, match=r'.* 3001 .*'):
                cluster.compress_files('some_name', ['some/path'], {'ko_file': 'file'})

        with patch('zlib.compress', return_value=b'compressed_test_content'):
            with patch.object(wazuh.core.cluster.cluster.logger, 'warning') as warning_logger:
                cluster.compress_files('some_name', ['some/path', 'another/path'], {'ko_file': 'file'})
                warning_logger.assert_called_with('Maximum zip size exceeded. Not all files will be compressed '
                                                  'during this sync.')

        with patch('zlib.compress', return_value='compressed_test_content'):
            with pytest.raises(WazuhError, match=r'.* 3001 .*'):
                cluster.compress_files('some_name', ['some/path', 'another/path'], {'ko_file': 'file'})

        with patch("json.dumps", side_effect=Exception):
            with patch('zlib.compress', return_value=b'test_content'):
                with pytest.raises(WazuhError, match=r'.* 3001 .*'):
                    cluster.compress_files('some_name', ['some/path'], {'ko_file': 'file'})


@pytest.mark.asyncio
@patch('wazuh.core.cluster.cluster.decompress_files', return_value="OK")
async def test_async_decompress_files(decompress_files_mock):
    """Check if the async wrapper is correctly working."""
    zip_path = '/foo/bar/'
    output = await cluster.async_decompress_files(zip_path=zip_path)
    assert output == decompress_files_mock.return_value
    decompress_files_mock.assert_called_once_with(zip_path, 'files_metadata.json')


@patch('zlib.decompress')
@patch('os.makedirs')
@patch('os.path.exists', side_effect=[False, True, True])
@patch('wazuh.core.cluster.cluster.remove')
@patch('wazuh.core.cluster.cluster.mkdir_with_mode')
@patch('json.loads', return_value="some string with files")
async def test_decompress_files_ok(json_loads_mock, mkdir_with_mode_mock, remove_mock, os_path_exists_mock,
                                   mock_makedirs, zlib_mock):
    """Check if the decompressing function is working properly."""
    zip_path = '/foo/bar/'
    compress_data = f'path{cluster.PATH_SEP}content{cluster.FILE_SEP}path2{cluster.PATH_SEP}content2'.encode()

    with patch('builtins.open', new_callable=mock_open, read_data=compress_data) as open_mock:
        handlers = [open_mock.return_value]*4
        open_mock.side_effect = handlers

        ko_files, zip_dir = cluster.decompress_files(compress_path=zip_path)
        assert ko_files == "some string with files"
        assert zip_dir == zip_path + 'dir'
        zlib_mock.assert_has_calls([call(b'content'), call(b'content2')])
        mock_makedirs.assert_called_once_with(zip_path + 'dir')
        json_loads_mock.assert_called_once()
        mkdir_with_mode_mock.assert_called_once_with(zip_dir)
        remove_mock.assert_called_once_with(zip_path)
        assert open_mock.call_args_list == [call('/foo/bar/', 'rb'), call('/foo/bar/dir/path', 'wb'),
                                            call('/foo/bar/dir/path2', 'wb'), call('/foo/bar/dir/files_metadata.json')]


@patch('shutil.rmtree')
@patch('zlib.decompress', return_value=Exception)
@patch('wazuh.core.cluster.cluster.mkdir_with_mode')
async def test_decompress_files_ko(mkdir_with_mode_mock, zlib_mock, rmtree_mock):
    """Check if the decompressing function raising the necessary exceptions."""

    # Raising the expected Exception
    zip_dir = '/foo/bar/'

    with pytest.raises(Exception):
        with patch('os.path.exists', return_value=True) as os_path_exists_mock:
            assert cluster.decompress_files(zip_dir) == "some string with files", zip_dir + "dir"
            mkdir_with_mode_mock.assert_called_once_with(zip_dir)
            zlib_mock.assert_called_once()
            os_path_exists_mock.assert_called_once()
            rmtree_mock.assert_called_once()

    with pytest.raises(Exception):
        with patch('builtins.open', mock_open(read_data=f'path{cluster.PATH_SEP}content'.encode())):
            with patch('os.path.exists', return_value=False):
                cluster.decompress_files(zip_dir)


@patch('wazuh.core.cluster.cluster.get_cluster_items')
@patch('wazuh.core.cluster.cluster.WazuhDBQueryAgents')
def test_compare_files(wazuh_db_query_mock, mock_get_cluster_items):
    """Check the different outputs of the compare_files function."""
    mock_get_cluster_items.return_value = {'files': {'key': {'extra_valid': True}}}

    seq = {'some/path3/': {'cluster_item_key': 'key', 'md5': 'md5 value'},
           'some/path2/': {'cluster_item_key': "key", 'md5': 'md5 value'}}
    condition = {'some/path2/': {'cluster_item_key': 'key', 'md5': 'md5 def value'},
                 'some/path4/': {'cluster_item_key': "key", 'md5': 'md5 value'}}

    # First condition
    with patch('wazuh.core.cluster.cluster.merge_info', return_values=[1, "random/path/"]):
        files, count = cluster.compare_files(seq, condition, 'worker1')
        assert count["missing"] == 1
        assert count["extra"] == 0
        assert count["extra_valid"] == 1
        assert count["shared"] == 1

    # Second condition
    condition = {'some/path5/': {'cluster_item_key': 'key', 'md5': 'md5 def value'},
                 'some/path4/': {'cluster_item_key': "key", 'md5': 'md5 value'},
                 os.path.relpath(common.GROUPS_PATH, common.WAZUH_PATH): {'cluster_item_key': "key",
                                                                          'md5': 'md5 value'}}

    files, count = cluster.compare_files(seq, condition, 'worker1')
    assert count["missing"] == 2
    assert count["extra"] == 0
    assert count["extra_valid"] == 3
    assert count["shared"] == 0
    wazuh_db_query_mock.assert_called_once_with(select=['id'], limit=None,
                                                filters={'rbac_ids': ['agent-groups']},
                                                rbac_negate=False)


@patch('wazuh.core.cluster.cluster.get_cluster_items')
@patch.object(wazuh.core.cluster.cluster.logger, "error")
@patch('wazuh.core.cluster.cluster.WazuhDBQueryAgents', side_effect=Exception())
def test_compare_files_ko(wazuh_db_query_mock, logger_mock, mock_get_cluster_items):
    """Check the different outputs of the compare_files function."""
    mock_get_cluster_items.return_value = {'files': {'key': {'extra_valid': True}}}

    seq = {'some/path3/': {'cluster_item_key': 'key', 'md5': 'md5 value'},
           'some/path2/': {'cluster_item_key': "key", 'md5': 'md5 value'}}
    condition = {'some/path2/': {'cluster_item_key': 'key', 'md5': 'md5 def value'},
                 'some/path4/': {'cluster_item_key': "key", 'md5': 'md5 value'},
                 os.path.relpath(common.GROUPS_PATH, common.WAZUH_PATH): {'cluster_item_key': "key",
                                                                          'md5': 'md5 value'}}

    # Test the exception
    with pytest.raises(Exception):
        cluster.compare_files(seq, condition, 'worker1')
        logger_mock.assert_called_once_with(
            f"Error getting agent IDs while verifying which extra-valid files are required: ")
        mock_get_cluster_items.assert_called_once_with()
        wazuh_db_query_mock.assert_called_once_with()


def test_clean_up_ok():
    """Check if the cleaning function is working properly."""

    with patch('os.path.join', return_value="some/path/"):
        with patch.object(wazuh.core.cluster.cluster.logger, "debug") as mock_logger:
            with patch('os.path.exists', return_value=False) as path_exists_mock:
                cluster.clean_up("worker1")
                mock_logger.assert_any_call("Removing 'some/path/'.")
                mock_logger.assert_any_call("Nothing to remove in 'some/path/'.")
                mock_logger.assert_called_with("Removed 'some/path/'.")

                path_exists_mock.return_value = True
                with patch('wazuh.core.cluster.cluster.listdir',
                           return_value=["c-internal.sock", "other_file.txt"]):
                    with patch('os.path.isdir', return_value=True) as is_dir_mock:
                        with patch('shutil.rmtree'):
                            cluster.clean_up("worker1")
                            mock_logger.assert_any_call("Removing 'some/path/'.")
                            mock_logger.assert_called_with("Removed 'some/path/'.")

                        is_dir_mock.return_value = False
                        with patch('wazuh.core.cluster.cluster.remove'):
                            cluster.clean_up("worker1")
                            mock_logger.assert_any_call("Removing 'some/path/'.")
                            mock_logger.assert_called_with("Removed 'some/path/'.")


def test_clean_up_ko():
    """Check if the cleaning function raising the exceptions properly."""
    error_cleaning = "Error cleaning up: stat: path should be string, bytes, os.PathLike or integer, not type."
    error_removing = f"Error removing '{Exception}': " \
                     f"'stat: path should be string, bytes, os.PathLike or integer, not type'."

    with patch('os.path.join') as path_join_mock:
        with patch.object(wazuh.core.cluster.cluster.logger, "error") as mock_error_logger:
            with patch.object(wazuh.core.cluster.cluster.logger, "debug") as mock_debug_logger:
                path_join_mock.return_value = Exception
                cluster.clean_up("worker1")
                mock_debug_logger.assert_any_call(f"Removing '{Exception}'.")
                mock_error_logger.assert_called_once_with(error_cleaning)

                with patch('os.path.exists', return_value=True):
                    with patch('wazuh.core.cluster.cluster.listdir',
                               return_value=["c-internal.sock", "other_file.txt"]):
                        with patch('shutil.rmtree', side_effect=Exception):
                            cluster.clean_up("worker1")
                            mock_debug_logger.assert_any_call(f"Removing '{Exception}'.")
                            mock_error_logger.assert_any_call(error_removing)
                            mock_debug_logger.assert_called_with(f"Removed '{Exception}'.")


@patch('wazuh.core.cluster.cluster.listdir', return_value=['005', '006'])
@patch('wazuh.core.cluster.cluster.stat')
def test_merge_info(stat_mock, listdir_mock):
    """Test merge agent info function."""
    stat_mock.return_value.st_mtime = time()
    stat_mock.return_value.st_size = len(agent_groups)

    with patch('builtins.open', mock_open(read_data=agent_groups)) as open_mock:
        files_to_send, output_file = cluster.merge_info('agent-groups', 'worker1', file_type='-shared')
        open_mock.assert_any_call(common.WAZUH_PATH + '/queue/cluster/worker1/agent-groups-shared.merged', 'wb')
        open_mock.assert_any_call(common.WAZUH_PATH + '/queue/agent-groups/005', 'rb')
        open_mock.assert_any_call(common.WAZUH_PATH + '/queue/agent-groups/006', 'rb')

        assert files_to_send == 2
        assert output_file == "queue/cluster/worker1/agent-groups-shared.merged"

        handle = open_mock()
        expected = f'{len(agent_groups)} 005 ' \
                   f'{get_date_from_timestamp(stat_mock.return_value.st_mtime)}\n'.encode() + agent_groups

        files_to_send, output_file = cluster.merge_info('agent-groups', 'worker1', files=["one", "two"],
                                                        file_type='-shared')

        assert files_to_send == 0


def test_unmerge_info():
    """Tests unmerge agent info function."""
    agent_info = f"23 005 2019-03-29 14:57:29.610934\n{agent_groups}".encode()

    with patch('builtins.open', mock_open(read_data=agent_info)):
        with patch('wazuh.core.cluster.cluster.stat') as stat_mock:
            # Make sure that the function is running correctly
            stat_mock.return_value.st_size = len(agent_info) - 5
            assert list(cluster.unmerge_info("destination/directory/", "path/file/", "filename")) == [
                ('queue/destination/directory/005', b"b'default,windows-serve", '2019-03-29 14:57:29.610934')]

            # Make sure that the Exception is being properly called
            stat_mock.return_value.st_size = len(agent_info)
            with patch.object(wazuh.core.cluster.cluster.logger, "warning") as mock_logger:
                list(cluster.unmerge_info("destination/directory/", "path/file/", "filename"))
                mock_logger.assert_called_once_with("Malformed file (not enough values to unpack "
                                                    "(expected 3, got 1)). Parsed line: rs'. "
                                                    "Some files won't be synced")


@pytest.mark.asyncio
async def test_run_in_pool():
    """Test if the function is running in a process pool if it exists."""

    def mock_callable(*args, **kwargs):
        """Mock function."""
        return "Mock callable"

    class LoopMock:
        """Mock class."""

        @staticmethod
        def partial(f, *args, **kwargs):
            """Mock function."""
            return "callable mock"

        @staticmethod
        async def run_in_executor(pool, partial=partial):
            """Mock method."""
            return None

    # Test the first condition
    with patch('wazuh.core.cluster.cluster.wait_for', return_value="OK") as wait_for_mock:
        assert await cluster.run_in_pool(LoopMock, LoopMock, mock_callable, None) == wait_for_mock.return_value
        wait_for_mock.assert_called_once()

    # Test the second condition
    assert await cluster.run_in_pool(LoopMock, None, mock_callable, None) == "Mock callable"
