*** Settings ***
Resource    resources/common.robot

Test Setup      Setup
Test Teardown   Teardown

Library     document_ttl.py

*** Variables ***
${CLIENT_PLATFORM}

*** Test Cases ***
Verify TTL Docs Purged
    # Implementation option 1: pyobjc, jython, ironpython
    # Implementation option 2: rest API proxy (RPC), SOAP listener, http://robotframework.org/robotframework/latest/RobotFrameworkUserGuide.html#remote-protocol
    # Implementation option 3: Native app for each platform
    Launch Listener     ${CLIENT_PLATFORM}
    ${db} =   Create Client Db  test-db
    Log to Console  ${db}
    Create Client Docs with ttl  ${db}
    Wait ttl + 100ms
    Check client docs purged    ${db}



*** Keywords ***
Setup
   Log To Console      Setting up ...


Teardown
   Log To Console  Tearing down ...
   Terminate All Processes
