#!/usr/bin/env python3
# _*_ coding: utf-8

import configparser
import datetime

from kanboard import Kanboard

import json2kanboard

# Import configuration
config = configparser.ConfigParser()
config.read("demo.example.conf")

# Create Kanboard API instance
kanboard_instance = Kanboard(
    config.get("kanboard","url"), 
    config.get("kanboard","user"), 
    config.get("kanboard","password") 
)

# Map roles in the JSON file to task owners
roles = {
  'ROLE_MANAGER': 'user_b'
  }

# Create Kanboard project
json2kanboard.create_project(
  "onboarding_project.demo.json",
  kanboard_instance,
  project_title = "TEST_PROJECT",
  project_identifier = "TEST_PROJECT_ID",
  due_date = datetime.date(2020, 1, 1),
  roles = roles,
  keys = ['key1']
  )
