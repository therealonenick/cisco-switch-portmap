#!/usr/bin/python
# Use this to look through the DB and identify counts

#define our debug flag first as this will dictacte if we pull in other modules
debug = 1
interfaceNameBuild = ''

#Import our modules
import os
import sys
import time
import sqlite3
from sqlite3 import Error
import serial
import glob
if debug == 1:
    import traceback
    from pprint import pprint, pformat



#Setup dictionary for Switches
logDir = "logs"
outputDir = "output"
dbDir = "db"
dbFileName = "projectData.db"
inputFile = ''

def db_conn(db_file):
    try:
        conn = sqlite3.connect(db_file)
        #conn = sqlite3.connect(':memory:') #Use this if you want to run in Memory instead.
        return conn
    except Error as e:
        print(e)

def dbTableSetup(conn, tableSQL):
    try:
        c = conn.cursor()
        c.execute(tableSQL)
    except Error as e:
        print(e)

def dbSelect(conn,selectSql):
    try:
        c = conn.cursor()
        c.execute(selectSql)
        rows = c.fetchall()
        return rows

    except Error as e:
        print(e)

def dbTableInsert(conn,tableInsert):
    try:
        c = conn.cursor()
        c.execute(tableInsert)
        conn.commit()
        return c.lastrowid

    except Error as e:
        print(e)

sqlConn = db_conn(dbDir+"/"+dbFileName)


closetListSql = str("SELECT DISTINCT(closet) FROM switches")
closetList = dbSelect(sqlConn,closetListSql)

for closet in closetList:
    accessVlan = []
    voiceVlan = []
    nativeVlan = []
    allowedVlan = []
    pruningVlan = []
    closet = closet[0]
    #closetListCountSql = str("SELECT * FROM portDiscovery INNER JOIN switches ON portDiscovery.ip = switches.currentIP WHERE switches.closet='{}'").format(closet)

    accessCountSql = str("SELECT DISTINCT(portDiscovery.accessVlan) FROM portDiscovery INNER JOIN switches ON portDiscovery.ip = switches.currentIP WHERE switches.closet='{}'").format(closet)
    voiceCountSql = str("SELECT DISTINCT(portDiscovery.voiceVlan) FROM portDiscovery INNER JOIN switches ON portDiscovery.ip = switches.currentIP WHERE switches.closet='{}'").format(closet)
    allowedCountSql = str("SELECT DISTINCT(portDiscovery.allowedVlan) FROM portDiscovery INNER JOIN switches ON portDiscovery.ip = switches.currentIP WHERE switches.closet='{}'").format(closet)
    pruningCountSql = str("SELECT DISTINCT(portDiscovery.pruningVlan) FROM portDiscovery INNER JOIN switches ON portDiscovery.ip = switches.currentIP WHERE switches.closet='{}'").format(closet)
    nativeCountSql = str("SELECT DISTINCT(portDiscovery.nativeVlan) FROM portDiscovery INNER JOIN switches ON portDiscovery.ip = switches.currentIP WHERE switches.closet='{}'").format(closet)
    accessVlanCount = dbSelect(sqlConn,accessCountSql)
    voiceVlanCount = dbSelect(sqlConn,voiceCountSql)
    allowedVlanCount = dbSelect(sqlConn,allowedCountSql)
    pruningVlanCount = dbSelect(sqlConn,pruningCountSql)
    nativeVlanCount = dbSelect(sqlConn,nativeCountSql)

    print("======================================================\r\n")
    msg = str("Closet: {}").format(closet)
    print(msg)
    print("Access Vlans:")
    print(accessVlanCount)
    print("Voice Vlans:")
    print(voiceVlanCount)
    print("Pruning Vlans:")
    print(pruningVlanCount)
    print("Allowed Vlans:")
    print(allowedVlanCount)
    print("Native Vlans:")
    print(nativeVlanCount)
    print("======================================================\r\n")

sqlConn.close()
sys.exit()
