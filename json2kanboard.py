#!/usr/bin/env python3
# _*_ coding: utf-8

import datetime
import logging
import random
import json

import sys


'''
import datetime
import copy
import logging
import urllib.parse
import ssl
import sys

sys.path.insert(0, '../workbookapi/')

import ldap3
import configparser
'''

from kanboard import Kanboard

# Valid user roles in a Kanboard project
KANBOARD_ROLES = (
  'project-member',
  'project-viewer',
  'project-manager'
  )

def create_project(
    project_file,
    kb,
    project_identifier = None,
    project_owner = None,
    project_title = None,
    task_owner = None,
    due_date = None,
    roles = {} 
    ):
  '''
  Creates a Kanboard project with tasks from a JSON file.
  
  If a task owner is not an assignable Kanboard user, the
  project owner will be added as a project-manager and will be
  the owner of the task.
  
  project_file: The JSON file describing the project
  
  kb: The Kanboard instance to use 
  
  identifier: A unique identifier for the project.
  if identifier is not supplied, no identifier will be set for
  the project. Of a project with the identifier exists, it will
  not be created.

  project_owner: The Kanboard username of the owner of the project.
  If not set, the owner will be the Kanboard username in the field 'owner'
  in the project_file. If the owner is not a valid Kanboard user, the project
  will not be created. If owner is not a Kanboard user (or it is not set)
  the project will not be created.
  
  project_name: The the title of the project.
  If unset, it will be read from the field 'title' in the project_file.
  
  task_owner: Username of a Kanboard user to own all tasks.
  If not set, the owner will be the owner defined for the task in the
  project_file. If no owner is defined, or the owner name does not match
  a Kanboard user, the task will be the project owner.
  
  due_date = The due date of the project. If a task has the field 'due_date'
  the value must be an integer. Of it is negative, the due date of the task
  is x days before the project due date. If it is positive, the due date
  is x days after the project due date. If the due date of any task is
  after the project due data, the project due date will be set to that date.
  '''

  # This user will own all tasks
  all_tasks_owner = task_owner

  # Get all Kanboard users
  users = kb.get_all_users()

  # A dictionary of users with username as key
  users_by_username = {u['username']:u for u in kb.get_all_users()}
  
  # Get all Kanboard groups
  groups_by_name = {g['name']:g for g in kb.get_all_groups() }
  
  # Add list of members to groups
  for group_data in groups_by_name.values():
    group_data['members'] = kb.get_group_members(
      group_id = group_data['id']
      )

  # Keep track of latest due date
  latest_due_date = due_date

  # Project identifier must be unique
  if project_identifier:
    r = kb.get_project_by_identifier(identifier = project_identifier)
    if r:
      logging.error("Error: identifier '{}' not unique. Not creating project"
        .format(project_identifier))
      return None

  #FIXME: Identifier is alphanumeric only?

  # Load the project data from the JSON file
  with open(project_file) as config_file:
      project_data = json.load(config_file)


  # Get project title from JSON if not supplied
  if not project_title:
    project_title = project_data.get('title', None)

  # Abort if no project name
  if not project_title:
    logging.error("Project has no title"
      .format(project_title))
    return None

  # Get owner from JSON if not supplied to function
  if not project_owner:
      project_owner = project_data.get('owner', None)

  # Try to get the Kanboard user matching the name of the project owner
  project_owner = users_by_username.get(project_owner, None)

  # Abort if project manager is not a Kanboard user
  if not project_owner:
    # FIXME: JSON owner?
    # FIXME: Function owner?
    logging.error("Owner '{}' for project '{}' is not a Kanboard user"
      .format(project_owner, project_title))
    return None

  logging.debug("Project owner is '{}' for project {}"
    .format(project_owner['name'], project_title))
    
  # FIXME: Notification?

  # FIXME: Support for swimlanes?

  # Create project in Kanboard
  new_project_id = kb.create_project(
    name = project_title,
    description = project_data.get('description', None),
    owner_id = project_owner['id'],
    identifier = project_identifier
  )

  # Abort if project not created
  if not new_project_id:
    logging.error("Could not create project '{}' with owner '{}' in Kanboard"
      .format(project_title, project_owner['name']))
    return None
  else:
    logging.info("Created project '{}' with owner '{}' and id '{}' in Kanboard"
      .format(project_title, project_owner['name'], new_project_id))

  # Get all columns in board
  project_columns = kb.get_columns(
    project_id = new_project_id
    )

  # Throw an error if we got no list
  if not project_columns:
    logging.error("Could not get project columns in project '{}' (ID: {})"
      .format(project_title, new_project_id))
  else:
    pass
    # FIXME: Should we abort here?

  # Create dict of columns by position
  # FIXME: Could be by name?
  project_columns_by_position = {c['position']:c for c in project_columns}


  # Add all users as members of the board
  for u in project_data.get('users', []):
    
    # Ignore user if not a Kanboard user
    if u['name'] not in users_by_username:
      logging.error("User '{}' is not a Kanboard user in project '{}'"
        .format(u['name'], project_title))
      continue
    
    # Ignore user if role is invalid
    if u['role'] not in KANBOARD_ROLES:
      logging.error("User '{}' has invalid role '{}' in project '{}'"
        .format(u['name'], u['role'], project_title))
      continue

    # Add users to project
    r = kb.add_project_user(
      project_id = new_project_id,
      user_id = users_by_username[u['name']]['id'],
      role = u['role']
      )
    
    # Log result
    if r:
      logging.info("Added user '{}' with role '{}'to Kanboard project '{}'"
      .format(u['name'], u['role'], project_title))
    else:
      logging.error("Could not add user '{}' with role '{}'to Kanboard project '{}'"
        .format(u['name'], u['role'], project_title))

  # Get users who can be assigned task in the project
  assignable_users_by_id = kb.get_assignable_users(
    project_id = new_project_id
    )

  # Error and empty dist if we failed getting the assignable users
  if not assignable_users_by_id:
    logging.error("Could not get assignable users in project '{}'"
      .format(project_title))
      
    # We have no assignable users, so fall back to empty dict
    assignable_users_by_id = {}

  # Create tasks
  for t in project_data['tasks']:
    
    # Abort if task has no title
    if not t.get('title'):
      logging.error("Can not create task in project '{}' because of missing title"
        .format(new_project_id))
      continue

    # FIXME: If owner is a list?
    task_owner = None
    
    # Get owner of all tasks if parsed to this function
    # Will override task owners in JSON
    if all_tasks_owner:
      task_owner = users_by_username.get(all_task_owner, {})

    # If an owner is specified in JSON
    elif t.get('owner', None):
      
      # If the owner is a group name, we will pick a random member
      # and substitute the owner name with a random member of the group
      
      # Try to get a group with the name of the task owner
      group = groups_by_name.get(t['owner'], None)
      
      # If we have a group with members
      if group and len(group['members']) > 0:
        
        # Set random group member as task_owner
        task_owner = random.choice(group['members'])

        # Add group member to Kanboard project
        if task_owner['id'] not in assignable_users_by_id:
          r = kb.add_project_user(
            project_id = new_project_id,
            user_id = task_owner['id'],
            role = 'project-member'
            )
        
          if r:
            logging.info("Adding user '{}' to project '{}' because of membership of group '{}'"
              .format(task_owner['name'], project_title, group['name']))
          else:
            logging.error("Could not add user '{}' to project '{}' because of membership of group '{}'"
              .format(task_owner['name'], project_title, group['name']))
  
          # Update list of users who can be assigned task in the project
          assignable_users_by_id = kb.get_assignable_users(
            project_id = new_project_id
            )
        
      else:  
        # Get matching Kanboard user if not a group
        task_owner = users_by_username.get(t['owner'], {})
      
      # FIXME: Should all task owners not be added?
      # If not, you MUST add single users (Non group) through the JSON-file.
      
      # Log if there was no matching user
      if not task_owner:
        logging.warning("Task owner '{}' from JSON is not a Kanboard user."
          .format(t['owner']))


    # If task owner was not in JSON or parsed to us, or the task owner
    # had no matching Kanboard user, the task owner will be the project owner
    if not task_owner:
      task_owner = project_owner

    # If the task owner is not an assignable user in the project,
    # Fall back to project owner
    if task_owner['id'] not in assignable_users_by_id:
      logging.error("Task owner '{}' is not an assignable user in project '{}'"
        .format(task_owner['name'], project_title))

      # Project owner will be the task owner
      task_owner = project_owner

      # Add the project owner as a project manager
      r = kb.add_project_user(
        project_id = new_project_id,
        user_id = task_owner['id'],
        role = 'project-manager'
        )
      
      # Log results and update assignable users
      if r:
        logging.warning("Added project owner '{}' as '{}' in project '{}'"
          .format(task_owner['name'], 'project-manager', project_title))

        # Update list of assignable users in the project
        assignable_users_by_id = kb.get_assignable_users(
          project_id = new_project_id
          )
      else:
        logging.error("Could not add project owner '{}' as '{}' in project '{}'"
          .format(task_owner['name'], 'project-manager', project_title))


    # Set task due date
    if due_date:
      
      # Default is the project due date
      task_due_date = due_date

      try:
        # Modify due date based on JSON data
        task_due_date += datetime.timedelta(days=int(t.get('due_date', 0)))
      except:
        logging.error("Could not modify due date with value '{}' from JSON in project '{}'"
          .format(t['due_date'], project_title))

      # Update projects latest due date
      if latest_due_date < task_due_date:
        latest_due_date = task_due_date
      
      # Convert due date to string
      task_due_date = task_due_date.isoformat()

    else:

      # Empty string if no due_date
      task_due_date = ''

    # Task collumn. Fallback to 1 (Leftmost)
    task_col = project_columns_by_position.get(t.get('column', '1'), '1')
    
    # Create the task
    new_task_id = kb.create_task(
      project_id = new_project_id,
      title = t.get('title',''),
      description = t.get('description', ''),
      owner_id = task_owner.get('id', ''),
      color_id = t.get('color', ''),
      tags = t.get('tags', []),
      date_due = task_due_date,
      #date_started = task_due_date,
      column_id = task_col['id']
      )

    if new_task_id:
      logging.info("Created task '{}' with owner '{}' in project '{}' with id '{}'."
        .format(t['title'], task_owner['name'], project_title, new_project_id))
    else:
      logging.error("Could not create task '{}' with owner '{}' in project '{}' with id '{}'."
        .format(t['title'], task_owner['name'], project_title, new_project_id))

    # Loop through subtasks
    for st in t.get('subtasks', []):
      
      # Create the subtask
      r = kb.create_subtask(
        task_id = new_task_id,
        title = st['title'],
      )
      
      # Log the results
      if r:
        logging.info("Created subtask '{}' in project '{}'"
          .format(st['title'], project_title))
      else:
        logging.error("Could not create subtask '{}' in project '{}'"
          .format(st['title'], project_title))

  # FIXME: Update project due date
  #r = kb.update_project(latest_due_date:
