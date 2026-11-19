"""Adapter layer: one small interface per outside system, each with a MOCK and a REAL stub.

The rest of the code only ever calls the interface (e.g. `adapters.chat.post_message`).
Switching from mock to live is a configuration change in `build()` below, not a rewrite.

  system            interface (what we call)        mock (default)     real (needs credentials)
  Ashby (ATS)       get_application                 MockAshby          AshbyAPI
  BambooHR (HRIS)   create_employee / get_employee  MockBambooHR       BambooHRAPI
  Slack             post_message                    MockSlack (outbox) SlackWebhook (SLACK_WEBHOOK_URL)
  IT tickets        create_ticket                   MockITSM           JiraServiceDeskAPI
  Okta (identity)   create_user                     MockOkta           OktaAPI

HONEST STATUS: the mocks are what the demo runs. The REAL classes build the correct
request shape from each vendor's public docs, but have NOT been run against a live
account (no live credentials were used to build this).
"""
import os
from dataclasses import dataclass

from .ats import AshbyAPI, MockAshby
from .chat import MockSlack, SlackWebhook
from .hris import BambooHRAPI, MockBambooHR
from .itsm import JiraServiceDeskAPI, MockITSM, MockOkta, OktaAPI


@dataclass
class Adapters:
    ats: object
    hris: object
    chat: object
    itsm: object
    idp: object


def build(conn) -> Adapters:
    """Pick mock or real for each system from environment variables."""
    env = os.environ.get
    return Adapters(
        ats=AshbyAPI(env("ASHBY_API_KEY")) if env("ASHBY_API_KEY") else MockAshby(conn),
        hris=BambooHRAPI(env("BAMBOOHR_SUBDOMAIN"), env("BAMBOOHR_API_KEY"))
        if env("BAMBOOHR_API_KEY") and env("BAMBOOHR_SUBDOMAIN") else MockBambooHR(conn),
        chat=SlackWebhook(env("SLACK_WEBHOOK_URL")) if env("SLACK_WEBHOOK_URL") else MockSlack(),
        itsm=JiraServiceDeskAPI(env("JSM_BASE_URL"), env("JSM_EMAIL"), env("JSM_API_TOKEN"))
        if env("JSM_API_TOKEN") and env("JSM_BASE_URL") else MockITSM(conn),
        idp=OktaAPI(env("OKTA_ORG_URL"), env("OKTA_API_TOKEN")) if env("OKTA_API_TOKEN") and env("OKTA_ORG_URL") else MockOkta(),
    )
