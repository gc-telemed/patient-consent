# Copyright 2017 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ------------------------------------------------------------------------------
import logging

from sanic import Blueprint
from sanic import response

from rest_api.ehr_common import transaction as ehr_transaction
from rest_api.consent_common import transaction as consent_transaction
from rest_api import general, security_messaging
from rest_api.errors import ApiBadRequest, ApiInternalError

INVESTIGATORS_BP = Blueprint('investigators')

logging.basicConfig(level=logging.DEBUG)
LOGGER = logging.getLogger(__name__)


@INVESTIGATORS_BP.get('investigators')
async def get_all_investigators(request):
    """Fetches complete details of all Accounts in state"""
    res_json = general.get_response_from_trial(request, "/investigators")

    # client_key = general.get_request_key_header(request)
    # investigator_list = await security_messaging.get_investigators(request.app.config.INVESTIGATOR_VAL_CONN,
    #                                                                request.app.config.CONSENT_VAL_CONN, client_key)

    investigator_list_json = []
    if res_json['data']:
        for entity in res_json['data']:
            investigator_list_json.append({
                'public_key': entity['public_key'],
                'name': entity['name']
            })

    return response.json(body={'data': investigator_list_json},
                         headers=general.get_response_headers())


@INVESTIGATORS_BP.post('investigators')
async def register_investigator(request):
    """Updates auth information for the authorized account"""
    required_fields = ['name']
    general.validate_fields(required_fields, request.json)

    name = request.json.get('name')

    clinic_signer = request.app.config.SIGNER_INVESTIGATOR  # .get_public_key().as_hex()

    # Consent network

    client_txn = consent_transaction.create_investigator_client(
        txn_signer=clinic_signer,
        batch_signer=clinic_signer
    )

    batch, batch_id = consent_transaction.make_batch_and_id([client_txn], clinic_signer)

    await security_messaging.add_investigator(
        request.app.config.CONSENT_VAL_CONN,
        request.app.config.TIMEOUT,
        [batch])

    try:
        await security_messaging.check_batch_status(
            request.app.config.CONSENT_VAL_CONN, [batch_id])
    except (ApiBadRequest, ApiInternalError) as err:
        # await auth_query.remove_auth_entry(
        #     request.app.config.DB_CONN, request.json.get('email'))
        raise err

    # EHR network

    clinic_txn = ehr_transaction.create_investigator(
        txn_signer=clinic_signer,
        batch_signer=clinic_signer,
        name=name
    )
    batch, batch_id = ehr_transaction.make_batch_and_id([clinic_txn], clinic_signer)

    await security_messaging.add_investigator(
        request.app.config.INVESTIGATOR_VAL_CONN,
        request.app.config.TIMEOUT,
        [batch])

    try:
        await security_messaging.check_batch_status(
            request.app.config.INVESTIGATOR_VAL_CONN, [batch_id])
    except (ApiBadRequest, ApiInternalError) as err:
        # await auth_query.remove_auth_entry(
        #     request.app.config.DB_CONN, request.json.get('email'))
        raise err

    return response.json(body={'status': general.DONE},
                         headers=general.get_response_headers())


# @INVESTIGATORS_BP.post('investigators/import_screening_data')
# async def import_screening_data(request):
#     """Updates auth information for the authorized account"""
#     investigator_key = general.get_request_key_header(request)
#     client_signer = general.get_signer(request, investigator_key)
#     LOGGER.debug('request.json: ' + str(request.json))
#     data_list = request.json
#     data_txns = []
#     for data in data_list:
#         data_txn = ehr_transaction.add_data(
#             txn_signer=client_signer,
#             batch_signer=client_signer,
#             uid=data['id'],
#             height=data['height'],
#             weight=data['weight'],
#             a1c=data['A1C'],
#             fpg=data['FPG'],
#             ogtt=data['OGTT'],
#             rpgt=data['RPGT'],
#             event_time=data['event_time'])
#         data_txns.append(data_txn)
#
#     batch, batch_id = ehr_transaction.make_batch_and_id(data_txns, client_signer)
#
#     await security_messaging.import_screening_data(
#         request.app.config.VAL_CONN,
#         request.app.config.TIMEOUT,
#         [batch], investigator_key)
#
#     try:
#         await security_messaging.check_batch_status(
#             request.app.config.VAL_CONN, [batch_id])
#     except (ApiBadRequest, ApiInternalError) as err:
#         # await auth_query.remove_auth_entry(
#         #     request.app.config.DB_CONN, request.json.get('email'))
#         raise err
#
#     return response.json(body={'status': general.DONE},
#                          headers=general.get_response_headers())


# TODO Deprecated method
@INVESTIGATORS_BP.get('investigators/import_to_trial_data/<patient_pkey>/<ehr_id>')
async def import_screening_data(request, patient_pkey, ehr_id):
    """Updates auth information for the authorized account"""
    investigator_pkey = general.get_request_key_header(request)
    client_signer = general.get_signer(request, investigator_pkey)
    # LOGGER.debug('request.json: ' + str(request.json))
    # data_list = request.json
    # data_txns = []
    # for data in data_list:

    has_signed_inform_consent = \
        await security_messaging.has_signed_inform_consent(
            request.app.config.VAL_CONN,
            patient_pkey,
            investigator_pkey)

    if not has_signed_inform_consent:
        raise ApiBadRequest("No signed inform consent between patient '" +
                            patient_pkey + "' and investigator '" + investigator_pkey + "'")

    ehr = await security_messaging.get_ehr_by_id(request.app.config.VAL_CONN, patient_pkey, ehr_id)

    data_txn = ehr_transaction.add_data(
            txn_signer=client_signer,
            batch_signer=client_signer,
            uid=ehr.id,
            height=ehr.height,
            weight=ehr.weight,
            a1c=ehr.A1C,
            fpg=ehr.FPG,
            ogtt=ehr.OGTT,
            rpgt=ehr.RPGT,
            event_time=ehr.event_time)

    batch, batch_id = ehr_transaction.make_batch_and_id([data_txn], client_signer)

    await security_messaging.import_screening_data(
        request.app.config.VAL_CONN,
        request.app.config.TIMEOUT,
        [batch], investigator_pkey)

    try:
        await security_messaging.check_batch_status(
            request.app.config.VAL_CONN, [batch_id])
    except (ApiBadRequest, ApiInternalError) as err:
        # await auth_query.remove_auth_entry(
        #     request.app.config.DB_CONN, request.json.get('email'))
        raise err

    return response.json(body={'status': general.DONE},
                         headers=general.get_response_headers())


# Deprecated method?
@INVESTIGATORS_BP.get('investigators/request_inform_consent/<patient_pkey>')
async def request_inform_consent(request, patient_pkey):
    """Updates auth information for the authorized account"""
    client_key = general.get_request_key_header(request)
    client_signer = general.get_signer(request, client_key)
    grant_read_ehr_permission_txn = consent_transaction.request_inform_document_consent(
        txn_signer=client_signer,
        batch_signer=client_signer,
        patient_pkey=patient_pkey)

    batch, batch_id = ehr_transaction.make_batch_and_id([grant_read_ehr_permission_txn], client_signer)

    await security_messaging.request_inform_document_consent(
        request.app.config.VAL_CONN,
        request.app.config.TIMEOUT,
        [batch], client_key)

    try:
        await security_messaging.check_batch_status(
            request.app.config.VAL_CONN, [batch_id])
    except (ApiBadRequest, ApiInternalError) as err:
        # await auth_query.remove_auth_entry(
        #     request.app.config.DB_CONN, request.json.get('email'))
        raise err

    return response.json(body={'status': general.DONE},
                         headers=general.get_response_headers())


@INVESTIGATORS_BP.post('investigators/data/eligible')
async def set_eligible(request):
    client_key = general.get_request_key_header(request)
    required_fields = ['id', 'eligible']
    general.validate_fields(required_fields, request.json)

    uid = request.json.get('id')
    eligible = bool(request.json.get('eligible'))

    client_signer = request.app.config.SIGNER_INVESTIGATOR  # .get_public_key().as_hex()

    client_txn = ehr_transaction.set_eligible(
        txn_signer=client_signer,
        batch_signer=client_signer,
        uid=uid,
        eligible=eligible)

    batch, batch_id = ehr_transaction.make_batch_and_id([client_txn], client_signer)

    await security_messaging.set_eligible(
        request.app.config.VAL_CONN,
        request.app.config.TIMEOUT,
        [batch], client_key)

    try:
        await security_messaging.check_batch_status(
            request.app.config.VAL_CONN, [batch_id])
    except (ApiBadRequest, ApiInternalError) as err:
        # await auth_query.remove_auth_entry(
        #     request.app.config.DB_CONN, request.json.get('email'))
        raise err

    return response.json(body={'status': general.DONE},
                         headers=general.get_response_headers())
