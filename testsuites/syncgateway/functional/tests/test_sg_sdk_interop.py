import random

import pytest
from requests.exceptions import HTTPError

from couchbase.bucket import Bucket
from couchbase.exceptions import NotFoundError

from keywords.SyncGateway import sync_gateway_config_path_for_mode
from keywords.utils import log_info
from keywords.utils import host_for_url
from keywords import document
from libraries.testkit.cluster import Cluster
from keywords.MobileRestClient import MobileRestClient


@pytest.mark.sanity
@pytest.mark.syncgateway
@pytest.mark.sdk
@pytest.mark.changes
@pytest.mark.session
@pytest.mark.parametrize('sg_conf_name', [
    'sync_gateway_default_functional_tests'
])
def test_sdk_interop_unique_docs(params_from_base_test_setup, sg_conf_name):

    """
    Scenario:
    - Bulk create 'number_docs' docs from SDK with prefix 'sdk' and channels ['sdk']
    - Bulk create 'number_docs' docs from SG with prefix 'sg' and channels ['sg']
    - TODO: SDK: Verify docs (sg + sdk) are present
    - TODO: SG: Verify docs (sg + sdk) are there via _all_docs
    - TODO: SG: Verify docs (sg + sdk) are there via _changes 
    - Bulk update each doc 'number_updates' from SDK for 'sdk' docs
    - Bulk update each doc 'number_updates' from SG for 'sg' docs
    - TODO: SDK: Verify doc updates (sg + sdk) are present using the doc['content']['updates'] property
    - TODO: SG: Verify doc updates (sg + sdk) are there via _all_docs using the doc['content']['updates'] property and rev prefix
    - TODO: SG: Verify doc updates (sg + sdk) are there via _changes using the doc['content']['updates'] property and rev prefix
    - Bulk delete 'sdk' docs from SDK
    - Bulk delete 'sg' docs from SG
    - Verify SDK sees all docs (sg + sdk) as deleted
    - Verify SG sees all docs (sg + sdk) as deleted
    """

    cluster_conf = params_from_base_test_setup['cluster_config']
    cluster_topology = params_from_base_test_setup['cluster_topology']
    mode = params_from_base_test_setup['mode']

    sg_conf = sync_gateway_config_path_for_mode(sg_conf_name, mode)
    sg_admin_url = cluster_topology['sync_gateways'][0]['admin']
    sg_url = cluster_topology['sync_gateways'][0]['public']

    bucket_name = 'data-bucket'
    cbs_url = cluster_topology['couchbase_servers'][0]
    sg_db = 'db'
    number_docs = 1000
    number_updates = 10

    log_info('sg_conf: {}'.format(sg_conf))
    log_info('sg_admin_url: {}'.format(sg_admin_url))
    log_info('sg_url: {}'.format(sg_url))

    cluster = Cluster(config=cluster_conf)
    cluster.reset(sg_config_path=sg_conf)

    # Connect to server via SDK
    cbs_ip = host_for_url(cbs_url)
    bucket = Bucket('couchbase://{}/{}'.format(cbs_ip, bucket_name))

    # Create docs and add them via sdk
    sdk_doc_bodies = document.create_docs('sdk', number_docs, content={'foo': 'bar', 'updates': 1}, channels=['sdk'])
    sdk_docs = {doc['_id']: doc for doc in sdk_doc_bodies}
    sdk_doc_ids = [doc for doc in sdk_docs]
    bucket.upsert_multi(sdk_docs)

    # Create sg user
    sg_client = MobileRestClient()
    sg_client.create_user(url=sg_admin_url, db=sg_db, name='seth', password='pass', channels=['sg', 'sdk'])
    seth_session = sg_client.create_session(url=sg_admin_url, db=sg_db, name='seth', password='pass')

    # Create / add docs to sync gateway
    sg_docs = document.create_docs('sg', number_docs, content={'foo': 'bar', 'updates': 1}, channels=['sg'])
    sg_docs_resp = sg_client.add_bulk_docs(url=sg_url, db=sg_db, docs=sg_docs, auth=seth_session)
    sg_doc_ids = [doc['_id'] for doc in sg_docs]

    assert len(sg_docs_resp) == number_docs

    # Since seth has channels from 'sg' and 'sdk', verify that the sdk docs and sg docs show up in
    # seth's changes feed

    # TODO: SDK: Verify docs (sg + sdk) are present
    # TODO: SG: Verify docs (sg + sdk) are there via _all_docs
    # TODO: SG: Verify docs (sg + sdk) are there via _changes

    for i in range(number_updates):

        # Get docs and extract doc_id (key) and doc_body (value.value)
        sdk_docs_resp = bucket.get_multi(sdk_doc_ids)
        docs = {k: v.value for k, v in sdk_docs_resp.items()}

        # update the updates property for every doc
        for _, v in docs.items():
            v['content']['updates'] += 1

        # Push the updated batch to Couchbase Server
        bucket.upsert_multi(docs)

        # Get docs from Sync Gateway
        sg_docs_to_update_resp = sg_client.get_bulk_docs(url=sg_url, db=sg_db, doc_ids=sg_doc_ids, auth=seth_session)
        sg_docs_to_update = sg_docs_to_update_resp['rows']
        for sg_doc in sg_docs_to_update:
            sg_doc['content']['updates'] += 1

        # Bulk add the updates to Sync Gateway
        sg_docs_resp = sg_client.add_bulk_docs(url=sg_url, db=sg_db, docs=sg_docs_to_update, auth=seth_session)

    # Get docs from Sync Gateway
    sg_docs_to_update_resp = sg_client.get_bulk_docs(url=sg_url, db=sg_db, doc_ids=sg_doc_ids, auth=seth_session)
    sg_docs_to_update = sg_docs_to_update_resp['rows']

    # TODO: SDK: Verify doc updates (sg + sdk) are present using the doc['content']['updates'] property
    # TODO: SG: Verify doc updates (sg + sdk) are there via _all_docs using the doc['content']['updates'] property and rev prefix
    # TODO: SG: Verify doc updates (sg + sdk) are there via _changes using the doc['content']['updates'] property and rev prefix

    # Delete the sync gateway docs
    sg_client.delete_bulk_docs(url=sg_url, db=sg_db, docs=sg_docs_to_update, auth=seth_session)
    # TODO: assert len(try_get_deleted_rows) == number_docs * 2

    # Delete the sdk docs
    bucket.remove_multi(sdk_doc_ids)

    # Verify all docs are deleted on the sync_gateway side
    all_doc_ids = sdk_doc_ids + sg_doc_ids
    assert len(all_doc_ids) == 2 * number_docs

    # Check GET /db/doc_id
    for doc_id in all_doc_ids:
        with pytest.raises(HTTPError) as he:
            sg_client.get_doc(url=sg_url, db=sg_db, doc_id=doc_id, auth=seth_session)

        log_info(he.value.message)

        # u'404 Client Error: Not Found for url: http://192.168.33.11:4984/db/sg_0?conflicts=true&revs=true'
        assert he.value.message.startswith('404 Client Error: Not Found for url:')

        # Parse out the doc id
        # sg_0?conflicts=true&revs=true
        parts = he.value.message.split('/')[-1]
        doc_id_from_parts = parts.split('?')[0]

        # Remove the doc id from the list
        all_doc_ids.remove(doc_id_from_parts)

    # Assert that all of the docs are flagged as deleted
    # TODO: assert len(all_doc_ids) == 0

    # Check /db/_bulk_get
    all_doc_ids = sdk_doc_ids + sg_doc_ids
    try_get_bulk_docs = sg_client.get_bulk_docs(url=sg_url, db=sg_db, doc_ids=all_doc_ids, auth=seth_session)

    # TODO: assert len(try_get_bulk_docs["rows"]) == number_docs * 2

    for row in try_get_bulk_docs['rows']:
        assert row['id'] in all_doc_ids
        assert row['status'] == 404
        assert row['error'] == 'not_found'
        assert row['reason'] == 'deleted'

        # Cross off the doc_id
        all_doc_ids.remove(row['id'])

    # Verify all docs are deleted on the sdk side
    all_doc_ids = sdk_doc_ids + sg_doc_ids

    # Verify all docs are deleted on sdk, deleted docs should rase and exception
    for doc_id in all_doc_ids:
        with pytest.raises(NotFoundError) as nfe:
            bucket.get(doc_id)
        log_info(nfe.value)
        all_doc_ids.remove(nfe.value.key)

    # Assert that all of the docs are flagged as deleted
    assert len(all_doc_ids) == 0


@pytest.mark.sanity
@pytest.mark.syncgateway
@pytest.mark.sdk
@pytest.mark.changes
@pytest.mark.session
@pytest.mark.parametrize('sg_conf_name', [
    'sync_gateway_default_functional_tests'
])
def test_sdk_interop_shared_docs(params_from_base_test_setup, sg_conf_name):
    """
    Scenario:
    - Bulk create 'number_docs' docs from SDK with prefix 'doc_set_one' and channels ['shared']
    - Bulk create 'number_docs' docs from SG with prefix 'doc_set_two' and channels ['shared']
    - TODO: SDK: Verify docs (sg + sdk) are present
    - TODO: SG: Verify docs (sg + sdk) are there via _all_docs
    - TODO: SG: Verify docs (sg + sdk) are there via _changes 
    - Start concurrent updates:
        loop until sg map and sdk map are len 0
        - Maintain map of each doc id to number of updates for sg
        - Maintain map of each doc id to number of updates for sdk
        - Pick random doc from sg map
        - Try to update doc from SG
        - If successful and num_doc_updates == number_updates_per_client, mark doc as finished in sg tracking map
        - Pick random doc from sdk map
        - Try to update doc from SDK
        - If successful and num_doc_updates == number_updates_per_client, mark doc as finished in sdk tracking map
    - TODO: SDK: Verify doc updates (sg + sdk) are present using the doc['content']['updates'] property
    - TODO: SG: Verify doc updates (sg + sdk) are there via _all_docs using the doc['content']['updates'] property and rev prefix
    - TODO: SG: Verify doc updates (sg + sdk) are there via _changes using the doc['content']['updates'] property and rev prefix
    - Start concurrent deletes:
        loop until len(all_doc_ids_to_delete) == 0
            - List of all_doc_ids_to_delete
            - Pick random doc and try to delete from sdk
            - If successful, remove from list
            - Pick random doc and try to delete from sg
            - If successful, remove from list
    - Verify SDK sees all docs (sg + sdk) as deleted
    - Verify SG sees all docs (sg + sdk) as deleted
    """

    cluster_conf = params_from_base_test_setup['cluster_config']
    cluster_topology = params_from_base_test_setup['cluster_topology']
    mode = params_from_base_test_setup['mode']

    sg_conf = sync_gateway_config_path_for_mode(sg_conf_name, mode)
    sg_admin_url = cluster_topology['sync_gateways'][0]['admin']
    sg_url = cluster_topology['sync_gateways'][0]['public']

    bucket_name = 'data-bucket'
    cbs_url = cluster_topology['couchbase_servers'][0]
    sg_db = 'db'
    number_docs = 10
    number_updates_per_client = 5

    log_info('sg_conf: {}'.format(sg_conf))
    log_info('sg_admin_url: {}'.format(sg_admin_url))
    log_info('sg_url: {}'.format(sg_url))

    cluster = Cluster(config=cluster_conf)
    cluster.reset(sg_config_path=sg_conf)

    # # Connect to server via SDK
    # cbs_ip = host_for_url(cbs_url)
    # sdk_client = Bucket('couchbase://{}/{}'.format(cbs_ip, bucket_name))
    #
    # # Create docs and add them via sdk
    # sdk_doc_bodies = document.create_docs('doc_set_one', number_docs / 2, content={'foo': 'bar', 'updates': 1}, channels=['shared'])
    # sdk_docs = {doc['_id']: doc for doc in sdk_doc_bodies}
    # doc_set_one_ids = [doc for doc in sdk_docs]
    # sdk_docs_resp = sdk_client.upsert_multi(sdk_docs)
    # assert len(sdk_docs_resp) == number_docs / 2

    # Create sg user
    sg_client = MobileRestClient()
    sg_client.create_user(url=sg_admin_url, db=sg_db, name='seth', password='pass', channels=['shared'])
    seth_session = sg_client.create_session(url=sg_admin_url, db=sg_db, name='seth', password='pass')

    # Inject custom properties into doc template
    def update_prop():
        return {'updates': 0}

    # Create / add docs to sync gateway
    # TODO: REMOVEEEEEEEEEEE
    sg_docs = document.create_docs('doc_set_one', number_docs / 2, channels=['shared'], prop_generator=update_prop)
    sg_docs_resp = sg_client.add_bulk_docs(url=sg_url, db=sg_db, docs=sg_docs, auth=seth_session)
    doc_set_one_ids = [doc['_id'] for doc in sg_docs]
    assert len(sg_docs_resp) == number_docs / 2
    # TODO: REMOVEEEEEEEEEEEE ^^^^^^^^^^^^

    # Create / add docs to sync gateway
    sg_docs = document.create_docs('doc_set_two', number_docs / 2, channels=['shared'], prop_generator=update_prop)
    sg_docs_resp = sg_client.add_bulk_docs(url=sg_url, db=sg_db, docs=sg_docs, auth=seth_session)
    doc_set_two_ids = [doc['_id'] for doc in sg_docs]
    assert len(sg_docs_resp) == number_docs / 2

    import pdb
    pdb.set_trace()

    # TODO: SDK: Verify docs (sg + sdk) are present
    # TODO: SG: Verify docs (sg + sdk) are there via _all_docs
    # TODO: SG: Verify docs (sg + sdk) are there via _changes
    all_doc_ids = doc_set_one_ids + doc_set_two_ids

    # Build a dictionary of all the doc ids with default number of updates (1 for created)
    sg_docs_update_status = {doc_id: 1 for doc_id in all_doc_ids}
    sdk_docs_update_status = {doc_id: 1 for doc_id in all_doc_ids}
    assert len(sg_docs_update_status) == number_docs
    assert len(sdk_docs_update_status) == number_docs

    # Loop until each client has had a chance to update each doc 'sg_docs_update_status'
    while len(sg_docs_update_status) > 0 or len(sdk_docs_update_status) > 0:
        sg_random_doc_id = random.choice(list(sg_docs_update_status))
        sg_random_doc = sg_client.get_doc(url=sg_url, db=sg_db, doc_id=sg_random_doc_id, auth=seth_session)
        # Todo: Update
        # Todo: Delete key if updated 'number_updates_per_client' times
        sg_updated_doc = sg_client.update_doc(url=sg_url, db=sg_db, doc_id=sg_random_doc_id, auth=seth_session)
        log_info(sg_docs_update_status)


        del sg_docs_update_status[sg_random_doc_id]

        # TODO: Change to SDK
        # sdk_random_doc_id = random.choice(list(sdk_docs_update_status))
        sdk_random_doc_id = random.choice(list(sdk_docs_update_status))
        sdk_random_doc = sg_client.get_doc(url=sg_url, db=sg_db, doc_id=sdk_random_doc_id, auth=seth_session)
        # TODO: REMOVEEEEEEEEEEEE ^^^^^^^^^^^^

        log_info('SDK: Updated {}'.format(sdk_random_doc_id))

        log_info(sdk_docs_update_status)
        del sdk_docs_update_status[sdk_random_doc_id]

    import pdb
    pdb.set_trace()

