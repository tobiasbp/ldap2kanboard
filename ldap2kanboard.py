#!/usr/bin/env python3
# _*_ coding: utf-8

import configparser
from datetime import datetime, timezone
import ldap3
import logging
import re
import ssl
import sys

import kanboard
import json2kanboard

# Import configuration
config = configparser.ConfigParser()
config.read("ldap2kanboard.conf")

# Configure logging
logging.basicConfig(
    level = eval(config.get("logging", 'level')),
    filename = config.get("logging", 'file'),
    format='%(asctime)s:%(levelname)s:%(message)s'
)

# 
logging.info("Running ldap2kanboard.py")


# Create Kanboard API instance
kb = kanboard.Client(
    config.get("kanboard","url"), 
    config.get("kanboard","user"), 
    config.get("kanboard","password") 
)

# Create an LDAP instance
t = ldap3.Tls(validate=ssl.CERT_NONE)

server = ldap3.Server(
  config.get("ldap","url"),
  tls = t
)

con = ldap3.Connection(
  server,
  config.get("ldap","bind_dn"),
  config.get("ldap","password"),
  auto_bind=False
)

con.open()
con.start_tls()
con.bind()

# FIXME: Move these to config file
USER_START_DATE_FIELD = 'fdContractStartDate'
ONBOARDING_PROJECT_ID_PREFIX = 'ONBOARDING'

# The JSON file used for onboarding
ONBOARDING_JSON = config.get("json", "onboarding")

# Search for users
con.search(
  config.get("ldap", "search_base"),
  config.get("ldap", "search_filter"),
  attributes = [
    'uid',
    'cn',
    'userPassword',
    'uidNumber',
    USER_START_DATE_FIELD,
    'o',
    'title',
    'mail',
    'fdPrivateMail',
    'employeeType',
    'manager'
    ] 
)


# Create a dictionary of LDAP users with uid as key
ldap_users_by_uid = { str(u.uid):u for u in con.entries }


# The time is now
now = datetime.now(timezone.utc)


# Loop through LDAP users
for u in con.entries:

  # User's start date
  # FIXME: Non-pretty way og extracting value. Is there a better way?
  u_start_date = u[USER_START_DATE_FIELD].values[0]

  # If the user's start date is in the future
  if u_start_date > now:

    logging.debug("Check for existance of onboarding project for user '{}'"
      .format(u.cn))

    # Create onboarding project identifier
    project_identifier = ONBOARDING_PROJECT_ID_PREFIX + str(u.uidNumber)
    
    # Look for existing onboarding project
    r = kb.get_project_by_identifier(
      identifier = project_identifier
      )

    # Abort current iteration if project exists
    if r:
      logging.debug("Onboarding project exists for '{}'. Don't create."
        .format(u.cn))
      continue

    # Assume no roles
    roles = {}

    # Define placeholders
    placeholders = {
      'NEW_USER_NAME': u.cn,
      'NEW_USER_UID': u.uid,
      'NEW_USER_TITLE': u.title,
      'NEW_USER_TYPE': u.employeeType,
      'NEW_USER_COMPANY': u.o,
      'NEW_USER_START_DATE': u_start_date.strftime('%d-%m-%Y'),
      'NEW_USER_PRIVATE_MAIL': u.fdPrivateMail,
      'NEW_USER_WORK_MAIL': u.mail
      }

    # Pattern for extracting uid from a DN
    p = re.compile('uid=([a-z]+)')

    # Match object. None if no match
    m = p.match(str(u['manager']))

    # If we have a match
    if m:
      # Extract the uid from the managers DN
      u_manager_uid = m.group(1)

      # Add manager role
      roles['ROLE_MANAGER'] = u_manager_uid

      # Add manager name to placeholders
      placeholders['NEW_USER_MANAGER_NAME'] = \
        ldap_users_by_uid[u_manager_uid]['cn']

    else:
      # Warn if no manager
      print("No manager found for user ''".format(u.cn))


    # Project description with placeholders
    description = (
      "* Name: NEW_USER_NAME (NEW_USER_UID)\n" +
      "* Private email: NEW_USER_PRIVATE_MAIL\n" +
      "* Work email: NEW_USER_WORK_MAIL\n" +
      "* Company: NEW_USER_COMPANY\n" +
      "* Title: NEW_USER_TITLE\n" +
      "* Start date: NEW_USER_START_DATE\n" +
      "* People manager: NEW_USER_MANAGER_NAME")

    # Create the kanboard project
    json2kanboard.create_project(
      ONBOARDING_JSON,
      kb,
      project_description = description,
      project_identifier = project_identifier,
      due_date = u_start_date,
      roles = roles,
      placeholders = placeholders
      )

    # Log the completion of the project
    logging.info("Created onboarding project for '{}'"
      .format(u.cn))


# Log that we completed running the script.
logging.info("Completed ldap2lontrapunkt.py normally")
