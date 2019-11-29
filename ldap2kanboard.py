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
USER_END_DATE_FIELD = 'fdContractEndDate'
ONBOARDING_PROJECT_ID_PREFIX = 'ONBOARDING'
OFFBOARDING_PROJECT_ID_PREFIX = 'OFFBOARDING'
MY_TASKS_PROJECT_ID_PREFIX = 'MYTASKS'

# Days to offboarding for types of users
days_for_offboarding = {
  "employee": 4*7,
  "hours": 4*7,
  "freelancer": 1*7
}

# The JSON file used for onboarding
ONBOARDING_JSON = config.get("json", "onboarding")
OFFBOARDING_JSON = config.get("json", "offboarding")
MY_TASK_JSON = config.get("json", "my_tasks")

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
    USER_END_DATE_FIELD,
    'homePhone',
    'o',
    'title',
    'mail',
    'fdPrivateMail',
    'employeeType',
    'manager'
    ] 
)


# A dict of LDAP users with uid as key
ldap_users_by_uid = { str(u.uid):u for u in con.entries }

# A dict of Kanboard users with username (uid) as key 
kb_users_by_username = { u['username']: u for u in kb.get_all_users() }

# The time is now
now = datetime.date(datetime.now(timezone.utc))

#################################
# Sync LDAP users with Kanboard #
#################################
for u in con.entries:
  
  # User locked in LDAP
  if '!' in str(u.userPassword):

    logging.debug("LDAP user {} is locked".format(u.cn))

    # If the LDAP user is a Kanboard user
    if str(u.uid) in kb_users_by_username:

      # If account is currently active
      if int(kb_users_by_username[str(u.uid)]['is_active']) == 1:

        # Disable the locked user
        r = kb.disable_user(
          user_id = kb_users_by_username[str(u.uid)]['id']
        )
        
        # Log the result
        if r:
          logging.info("Disabled Kanboard user {} because the account is locked in LDAP".format(u.cn))
        else:
          logging.error("Could not disable Kanboard user {}.".format(u.cn))

  # User not locked in LDAP
  else:
  
    # User is not a Kanboard user
    if not str(u.uid) in kb_users_by_username:

        # Create Kanboard user from data in LDAP
        r = kb.create_ldap_user(
          username = str(u.uid)
          )
        
        # Log result
        if r:
          logging.info("Added ldap user to Kanboard: '{}' ({})".format(u.cn, u.uid))
        else:
          logging.error("Could not add ldap user to Kanboard: '{}' ({})".format(u.cn, u.uid))
    
    # User is a Kanboard user
    else:
      
      # Activate Kanboard user if not active
      if int(kb_users_by_username[str(u.uid)]['is_active']) == 0:
        
        # Activate inactive Kanboard user
        r = kb.enable_user(
          user_id = kb_users_by_username[str(u.uid)]['id']
        )
        
        # Log the result
        if r:
          logging.info("Re-enabled existing Kanboard user {}".format(u.cn))
        else:
          logging.error("Could not re-enable existing Kanboard user {}".format(u.cn))

# Reload a dict of Kanboard users with username (uid) as key 
kb_users_by_username = { u['username']: u for u in kb.get_all_users() }

#############################
# Update groups in Kanboard #
#############################

# FIXME: Update groups in Kanboard based on data in LDAP


################################
# Check Kanboard users in LDAP #
################################
'''
# Should we delete users not in LDAP? Not if we have more than one sync like now!
for u_uid, u_data in kb_users_by_username.items():
  if u_uid not in ldap_users_by_uid:
    logging.info("Not in LDAP: {} ({})"
      .format(u_data['name'], u_data['email'])
      )
'''

##############################
# Create onboarding projects #
##############################
for u in con.entries:

  # Ignore locked users
  if '!' in str(u.userPassword):
    logging.debug("Ignoring locked user '{}' is locked".format(u.cn))
    continue

  # User's start date
  u_start_date = datetime.date(u[USER_START_DATE_FIELD].value)
  
  # User's end date as string
  if u[USER_END_DATE_FIELD]:
    u_end_date = datetime.date(u[USER_END_DATE_FIELD].value).strftime('%d-%m-%Y')
  else:
    u_end_date = "None"

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
      'NEW_USER_END_DATE': u_end_date,
      'NEW_USER_PRIVATE_MAIL': u.fdPrivateMail,
      'NEW_USER_WORK_MAIL': u.mail,
      'NEW_USER_PRIVATE_PHONE': u.homePhone.value
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
      logging.warning("No manager found for user ''".format(u.cn))

    keys = [
      str(u.employeeType),
      str(u.o)
    ]

    # Project description with placeholders
    description = (
      "* Name: NEW_USER_NAME (NEW_USER_UID)\n" +
      "* Private email: NEW_USER_PRIVATE_MAIL\n" +
      "* Private phone: NEW_USER_PRIVATE_PHONE\n" +
      "* Work email: NEW_USER_WORK_MAIL\n" +
      "* Company: NEW_USER_COMPANY\n" +
      "* Title: NEW_USER_TITLE\n" +
      "* Start date: NEW_USER_START_DATE\n" +
      "* End date: NEW_USER_END_DATE\n" +
      "* Type: NEW_USER_TYPE\n" +
      "* People manager: NEW_USER_MANAGER_NAME"
      )

    # Create the kanboard project
    json2kanboard.create_project(
      ONBOARDING_JSON,
      kb,
      project_description = description,
      project_identifier = project_identifier,
      due_date = u_start_date,
      roles = roles,
      placeholders = placeholders,
      keys = keys
      )

    # Log the completion of the project
    logging.info("Created onboarding project for '{}'"
      .format(u.cn))

###############################
# Create offboarding projects #
###############################

for u in con.entries:

  # Ignore user if no end date
  if not u[USER_END_DATE_FIELD]:
    continue

  u_days_left = \
    (u[USER_END_DATE_FIELD].value - datetime.now(timezone.utc)).days
    #datetime.now(timezone.utc) - u[USER_END_DATE_FIELD].value


  # Abort if we don't know the offboarding time for the user time 
  if u.employeeType.value not in days_for_offboarding.keys():
    logging.error("User type '{}' for user '{}' is undefined"
      .format(u.employeeType, u.cn))
    continue


  # Is it time to offboard for this type of user?
  if u_days_left <= days_for_offboarding[u.employeeType.value]:

    # Create onboarding project identifier
    project_identifier = OFFBOARDING_PROJECT_ID_PREFIX + str(u.uidNumber)

    # Look for existing onboarding project
    r = kb.get_project_by_identifier(
      identifier = project_identifier
      )

    # Abort current iteration if project exists
    if r:
      logging.debug("Offboarding project exists for '{}'. Don't create."
        .format(u.cn))
      continue

    #print("User '{}({})' of type '{}' has end date in {} days."
    #  .format(u.cn, u.uid, u.employeeType, u_days_left))

    # The user's end date
    u_start_date = datetime.date(u[USER_START_DATE_FIELD].value)
    u_end_date = datetime.date(u[USER_END_DATE_FIELD].value)

    # Assume no roles
    roles = {}

    # Define placeholders
    placeholders = {
      'USER_NAME': u.cn.value,
      'USER_UID': u.uid.value,
      'USER_TITLE': u.title.value,
      'USER_TYPE': u.employeeType.value,
      'USER_COMPANY': u.o.value,
      'USER_START_DATE': u_start_date.strftime('%d-%m-%Y'),
      'USER_END_DATE': u_end_date.strftime('%d-%m-%Y'),
      'USER_PRIVATE_MAIL': u.fdPrivateMail.value,
      'USER_WORK_MAIL': u.mail.value
      }

    # Pattern for extracting uid from a DN
    p = re.compile('uid=([a-z]+)')

    # Match object. None if no match
    m = p.match(u['manager'].value)

    # If we have a match
    if m:
      # Extract the uid from the managers DN
      u_manager_uid = m.group(1)

      # Add manager role
      roles['ROLE_MANAGER'] = u_manager_uid

      # Add manager name to placeholders
      placeholders['USER_MANAGER_NAME'] = \
        ldap_users_by_uid[u_manager_uid]['cn'].value

    else:
      # Warn if no manager
      logging.warning("No manager found for user ''".format(u.cn))


    # Project description with placeholders
    description = (
      "* Name: USER_NAME (USER_UID)\n" +
      "* Private email: USER_PRIVATE_MAIL\n" +
      "* Work email: USER_WORK_MAIL\n" +
      "* Company: USER_COMPANY\n" +
      "* Title: USER_TITLE\n" +
      "* Start date: USER_START_DATE\n" +
      "* End date: USER_END_DATE\n" +
      "* Type: USER_TYPE\n" +
      "* People manager: USER_MANAGER_NAME"
      )

    # Keys used for matching tasks
    keys = [
      str(u.employeeType),
      str(u.o)
    ]

    # Create the kanboard project
    json2kanboard.create_project(
      OFFBOARDING_JSON,
      kb,
      project_description = description,
      project_identifier = project_identifier,
      due_date = u_end_date,
      roles = roles,
      placeholders = placeholders,
      keys = keys
      )

    # Log the completion of the project
    logging.info("Created offboarding project for '{}'"
      .format(u.cn))


#####################################
# Create personal Kanboard projects #
#####################################

for u in con.entries:

  # Demo: Only create for this user
  #if u.uid != 'plj':
  #  continue

  # Identifier for users personal project
  project_identifier = MY_TASKS_PROJECT_ID_PREFIX + str(u.uidNumber) 
  
  # Try to get existing Kanboard project
  r = kb.get_project_by_identifier(
    identifier = project_identifier
    )
  
  # Abort if personal project exists
  if r:
    logging.debug("Personal Kanboard project for user '{}' exists"
      .format(u.cn))
    continue
  
    
  # Create personal Kanboard project for user
  logging.info("Creating personal Kanboard project for user '{}'"
    .format(u.cn))

  # Keys used for matching tasks
  keys = [
    str(u.employeeType),
    str(u.o)
    ]

  # Ignore locked users
  if '!' in str(u.userPassword):
    logging.debug("Ignoring locked user '{}' is locked".format(u.cn))
    continue

  # Define placeholders
  placeholders = {
    'USER_NAME': u.cn,
    'USER_EMAIL': u.mail,
    }

  # Start date is now if start date is in the past
  u_start_date = max(
    datetime.now(timezone.utc),
    u[USER_START_DATE_FIELD].value
    )

  # Create the kanboard project
  json2kanboard.create_project(
    MY_TASK_JSON,
    kb,
    project_owner = str(u.uid),
    project_identifier = project_identifier,
    due_date = u_start_date,
    placeholders = placeholders,
    keys = keys
    )

  # Create personal Kanboard project for user
  logging.info("Created personal Kanboard project for user '{}'"
    .format(u.cn))


# Log that we completed running the script.
logging.info("Completed ldap2kontrapunkt.py normally")
