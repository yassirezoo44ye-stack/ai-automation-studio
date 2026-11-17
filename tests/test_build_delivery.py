import asyncio

import pytest
from fastapi import HTTPException

from app.core.build_delivery import validate_delivery
from app.core.commerce_builder import store_files


def test_transactional_interface_only_cannot_complete():
    with pytest.raises(HTTPException, match='backend'):
        validate_delivery('Build a CRM', {}, {'index.html': '<h1>Clients</h1>'}, 'serve .')


def test_store_is_structurally_checked_but_never_claimed_runtime_verified():
    result = validate_delivery('Build a store', {}, store_files(), 'python main.py')
    assert result['status'] == 'generated'
    assert result['structure_checked'] is True
    assert result['runtime_verified'] is False and result['deployed'] is False


def test_backend_without_persistence_cannot_complete():
    with pytest.raises(HTTPException, match='database'):
        validate_delivery('booking system', {}, {'main.py':'from fastapi import FastAPI\napp = FastAPI()', 'requirements.txt':'fastapi'}, 'python main.py')


def test_static_site_remains_supported():
    assert validate_delivery('A static portfolio', {}, {'index.html':'<h1>Portfolio</h1>'}, 'serve .')['requires_backend'] is False


def test_incomplete_generation_has_no_success_contract():
    with pytest.raises(HTTPException):
        validate_delivery('app', {}, {'main.py':'print(1)'}, '')


def test_deploy_without_driver_does_not_claim_success(tmp_path):
    from app.commands.builtin.deploy_cmd import deploy_handler
    from app.commands.context import CommandContext
    result = asyncio.run(deploy_handler(CommandContext(command='deploy', workspace=tmp_path, flags={'target':'render'})))
    assert not result.success
    assert result.error_code == 'DEPLOY_DRIVER_UNAVAILABLE'
