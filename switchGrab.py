#!/usr/bin/python

#define our debug flag first as this will dictacte if we pull in other modules
debug = 1
interfaceNameBuild = ''

#Import our modules
import os
import sys
import getpass
import time
import datetime
import csv
import re
import sqlite3
from sqlite3 import Error
from netmiko import ConnectHandler, NetMikoTimeoutException
from netmiko import NetMikoAuthenticationException
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
confDir = 'configs'
inputFile = ''
inputFiles = []
switches = {}
interfaceDict= {}
mapDataFile = ''
mapData = {}
loginSelection = 0
user = ''
pw = ''
#End system variabls

#Variables for new build option 3
mgtVlan = 1
domain = ''
defaultAccessVLAN = ''
consoleUsername = ''
consolePassword = ''

#End build options


logFileName = "logFile_"+datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d-%H_%M_%S')+".txt"
#Check and setup logging
if not os.path.exists(logDir):
    os.mkdir(logDir)
    msg = str("Directory {} Created").format(logDir)
    print(msg)
else:
    msg = str("Directory {} already exists").format(logDir)
    print(msg)

logFileStr = str("{}/{}").format(logDir,logFileName)
logFileStr = os.path.normpath(logFileStr)
logFile = open(logFileStr, "w")
#Check and setup output


#DB Directory
if not os.path.exists(dbDir):
    os.mkdir(dbDir)
    msg = str("Directory {} Created").format(dbDir)
    logFile.write(msg)
    print(msg)
else:
    msg = str("Directory {} already exists.  Flushing").format(dbDir)
    logFile.write(msg)
    print(msg)

#ConfigDirectories

if not os.path.exists(confDir):
    os.mkdir(confDir)
    msg = str("Directory {} Created").format(confDir)
    logFile.write(msg)
    print(msg)
else:
    msg = str("Directory {} already exists").format(confDir)
    logFile.write(msg)
    print(msg)

templateDir = 'template'
if not os.path.exists(confDir):
    os.mkdir(templateDir)
    msg = str("Directory {} Created").format(templateDir )
    logFile.write(msg)
    print(msg)
else:
    msg = str("Directory {} already exists").format(templateDir )
    logFile.write(msg)
    print(msg)

#Let us know that Debugging is enabled.
if debug == 1:
    msg = "Debugging Enabled.\n"
    print(msg)
    logFile.write(msg)
    msg = str("Envrionment Variables: {} \n").format(os.environ['NET_TEXTFSM'])
    print(msg)
    logFile.write(msg)

#Check Python version before continuing
pyVersion = sys.version_info
if pyVersion[0] < 3:
    msg = str("Must use Python3+.  Current Version: {}.{}.{}").format(pyVersion[0], pyVersion[1], pyVersion[2])
    #print("Must use Python3+.  Current Version: {}.{}.{}").format(pyVersion[0], pyVersion[1], pyVersion[2])
    print(msg)
    logFile.write(msg)
    sys.exit()


#Setup sqlite3

def dbCheck():
    #DB Directory
    if not os.path.exists(dbDir):
        os.mkdir(dbDir)
        msg = str("Directory {} Created").format(dbDir)
        logFile.write(msg)
        print(msg)
    else:
        msg = str("Directory {} already exists.  Flushing").format(dbDir)
        logFile.write(msg)
        print(msg)
        for dbFile in os.listdir(dbDir):
            try:
                dbFilePath = os.path.join(dbDir, dbFile)
                os.remove(dbFilePath)
            except Exception as e:
                print(e)
        msg = str("DB Directory Flushed.")
        logFile.write(msg)
        print(msg)

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

def dbTableInsert(conn,tableInsert):
    try:
        c = conn.cursor()
        c.execute(tableInsert)
        conn.commit()
        return c.lastrowid

    except Error as e:
        print(e)


def dbTableFlush(conn,tableName):
    try:
        deleteQ = str("DELETE FROM {}").format(tableName)
        print(deleteQ)
        c = conn.cursor()
        c.execute(deleteQ)
        conn.commit()

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

def cleanup(conn):
    try:
        c = conn.cursor()
        c.execute("VACUUM")
    except Error as e:
        print(e)

#Check the length of the port.  If its less than < its a MGT interface
def portCheck(port):

    portExplode = port.split("/")

    if not len(portExplode) < 2:
        return True
    else:
        return False

def switchStackCheck(ip):
    stackCheckSQL = str("SELECT COUNT(currentIP) FROM switches WHERE currentIP = '{}'").format(ip)
    stackCheckResult = dbSelect(sqlConn, stackCheckSQL)
    if stackCheckResult[0][0] > 1:
        return True
    else:
        return False

def DumpMacTable(conn,switch,table):
    #print(table)
    for mac in table:
        data = str("INSERT INTO mactables(switch, vlan, mac, type, port) VALUES ('{}', '{}', '{}', '{}', '{}')").format(switch, mac['vlan'], mac['destination_address'], mac['type'], mac['destination_port'])
        dbTableInsert(conn, data)

def DumpArpTable(conn,switch,table):
    #print(table)
    for arp in table:
        data = str("INSERT INTO arptables(switch, protocol, address, age, mac, type, interface) VALUES ('{}', '{}', '{}', '{}', '{}', '{}', '{}')").format(switch, arp['protocol'], arp['address'], arp['age'], arp['mac'], arp['type'], arp['interface'])
        dbTableInsert(conn, data)

def ConfigWrite(closet,hostname,config):
    configname = str("{}-{}.cfg").format(closet,hostname)
    configFile = str("{}/{}").format(confDir,configname)
    configFile = os.path.normpath(configFile)
    configwr = open(configFile, "w")
    for line in config:
        line = str("{}\r\n").format(line)
        configwr.write(line)
    configwr.close()
    #sys.exit()



#For sake of speed, taken from (and modified): https://stackoverflow.com/questions/12090503/listing-available-com-ports-with-python
def serial_ports():
    print("Looking for serial devices...\r\n")
    """ Lists serial port names

        :raises EnvironmentError:
            On unsupported or unknown platforms
        :returns:
            A list of the serial ports available on the system
    """
    if sys.platform.startswith('win'):
        ports = ['COM%s' % (i + 1) for i in range(256)]
    elif sys.platform.startswith('linux') or sys.platform.startswith('cygwin'):
        # this excludes your current terminal "/dev/tty"
        ports = glob.glob('/dev/tty[A-Za-z]*')
    elif sys.platform.startswith('darwin'):
        #ports = glob.glob('/dev/tty.*')
        ports = glob.glob('/dev/cu.*')
    else:
        raise EnvironmentError('Unsupported platform')

    result = []
    serialConnOpt = ''
    for port in ports:
        try:
            s = serial.Serial(port)
            s.close()
            result.append(port)
        except (OSError, serial.SerialException):
            pass
    while True:
        c = 1
        print("Please select the Serial device to use:\r\n")
        for r in result:
            opt = str("{}: {}").format(c, r)
            print(opt)
            c+=1
        try:
            serialSelection = input("Selection: \r\n")
        except ValueError:
            print("Not a number.  Please try again")
            continue
        else:
            serialSelection = int(serialSelection) - 1
            if result[serialSelection]:
                serialConnOpt = result[serialSelection]
                #print(serialConnOpt)
                break
            else:
                print(serialSelection)
                print('Invalid selection.\r\n')
    return serialConnOpt



def ConnectSerial(serialDevice):
    c = serial.Serial(
        port=serialDevice,
        baudrate="9600",
        parity="N",
        stopbits=1,
        bytesize=8,
        timeout=8
    )
    print(c)
    return c


def nPushConfigSerial(serialDevice,username,password,commands):
    serDevice = {
        'device_type': 'cisco_ios_serial',
        'username': username,
        'password': password,
        'secret': password,
        'serial_settings': {'port': serialDevice}
    }
    ####
    serConnect = ConnectHandler(**serDevice)
    if serConnect:
        expect_string = r"(>|#)"
        delay_factor = 1
        print("Connected to Serial!")
        serConnectOutput = serConnect.find_prompt()
        if serConnectOutput.endswith(">"):
            serConnect.enable()

        #serConnect.send_command('send *\r\n Hello from Script! \x1A', expect_string)
        for cmd in commands:
            #print(cmd)
            serConnect.send_command(cmd,expect_string,delay_factor)




def importSwitches(inputFile):
    #Read in the CSV and pull in all the data
    try:
        with open(inputFile, newline='') as switchFile: #Loop through each line
            switchList = csv.DictReader(switchFile)
            for switch in switchList:
                #
                #if debug == 1:
                #    msg = str("IP/Hostname: "+switch['host'])
                #    print(msg)
                #    logFile.write(msg)
                #
                host = switch['CurrentSwitchIP']
                currentSwitchName = switch['CurrentSwitchName']
                positionID = switch['CurrentSwitchPositionID']
                closet = switch['Closet']
                username = switch['user']
                password = switch['password']
                switchSql = str("INSERT INTO switches(closet, currentSwitchName, currentIP, positionID, username, password) VALUES ('{}', '{}', '{}', '{}', '{}', '{}' ); ").format(closet, currentSwitchName, host, positionID, username, password)
                #print(switchSql)
                dbTableInsert(sqlConn, switchSql)


    except TypeError:
        print("If you are seeing this error, you need Python 3+.")
        print("Running version: "+sys.version)
        if debug == 1:
            print("DEBUG:\n")
            print(traceback.format_exc())


def updateSwitches(inputFile):
    #Read in the CSV and pull in all the data
    try:
        with open(inputFile, newline='') as switchFile: #Loop through each line
            switchList = csv.DictReader(switchFile)
            for switch in switchList:
                #
                #if debug == 1:
                #    msg = str("IP/Hostname: "+switch['host'])
                #    print(msg)
                #    logFile.write(msg)
                #
                host = switch['CurrentSwitchIP']
                currentSwitchName = switch['CurrentSwitchName']
                closet = switch['Closet']
                currentSwitchPosition = switch['CurrentSwitchPosition']
                currentSwitchPositionID = switch['CurrentSwitchPositionID']
                newSwitchName = switch['NewSwitchName']
                newSwitchPosition = switch['NewSwitchPosition']
                newSwitchIP = switch['NewSwitchIP']
                newSubnetMask = switch['newSubnetMask']
                newDGW = switch['newDGW']
                newMgtVlan = switch['mgtVlan']
                newSwitchPosition = newSwitchPosition[1:] #Strip off the S
                #switchSql = str("INSERT INTO switches(closet, currentSwitchName, currentIP, positionID, username, password) VALUES ('{}', '{}', '{}', '{}', '{}', '{}' ); ").format(closet, currentSwitchName, host, positionID, username, password)
                switchSql = str("UPDATE switches SET closet = '{}', position = '{}', positionID = '{}', newSwitchName = '{}', newSwitchIP = '{}', newSwitchPosition = '{}', newSubnetMask='{}', newDGW='{}', mgtVlan='{}' WHERE closet = '{}' AND positionID = '{}'").format(closet, currentSwitchPosition, currentSwitchPositionID, newSwitchName, newSwitchIP, newSwitchPosition, newSubnetMask, newDGW, newMgtVlan, closet, currentSwitchPositionID)

                dbTableInsert(sqlConn, switchSql)
                #print(switchSql)
                #switchUpdate = dbTableInsert(sqlConn, switchSql)



                sqlOrderSql = str("SELECT * FROM switches where currentIP = '{}' ORDER BY position").format(host)
                #sqlOrderSql = str("SELECT * FROM switches where currentIP = '{}' ORDER BY position").format(host)
                sqlOrderResult = dbSelect(sqlConn, sqlOrderSql)
                #print(sqlOrderResult)
                stackID = sqlOrderResult[0][5]
                #pprint(sqlOrderResult)
                for uswitch in sqlOrderResult:
                    #print(uswitch)
                    if host=='IGNORE':
                        updateStackSql = str("UPDATE switches SET curStackID = '{}' WHERE id={}").format(currentSwitchPositionID,uswitch[0])
                    else:
                        updateStackSql = str("UPDATE switches SET curStackID = '{}' WHERE id={}").format(stackID,uswitch[0])
                    #print("Stack Update: "+updateStackSql)
                    dbTableInsert(sqlConn, updateStackSql)


    except TypeError:
        print("If you are seeing this error, you need Python 3+.")
        print("Running version: "+sys.version)
        if debug == 1:
            print("DEBUG:\n")
            print(traceback.format_exc())

#This is dirty and should corrected with proper import after this project is over.
#Created to handle the problem of properly indentifing the X in giX/0/Y when stacks are out of physical order and not primary in the list during import.
def CorrectStackInterfaceProblem():
    print("Fixing Stack Interface Problem...")
    oldSwitchSql = str("SELECT DISTINCT(currentIP) FROM switches WHERE currentIP != 'IGNORE'")
    oldSwitchResult = dbSelect(sqlConn, oldSwitchSql)

    for switch in oldSwitchResult:
        switch = switch[0]
        sqlInsert = ''
        if switchStackCheck(switch):
            stackListSql = str("SELECT * FROM switches where currentIP = '{}'").format(switch)
            stackListResult = dbSelect(sqlConn, stackListSql)
            for s in stackListResult:
                name = s[2]
                nameExplode = name.split("-")
                #Find last element, that is where our ID is..
                c = len(nameExplode)
                stackIntID = nameExplode[c-1]
                #Lets update the DB
                sqlInsert = str("UPDATE switches SET stackIntID={} WHERE id={} ").format(stackIntID,s[0])
                dbTableInsert(sqlConn, sqlInsert)
        else:
            sqlInsert = str("UPDATE switches SET stackIntID=1 WHERE currentIP='{}' ").format(switch)
            dbTableInsert(sqlConn, sqlInsert)

def GrabIntStackID(ip,position):
    grabSql = str("SELECT stackIntID from switches WHERE currentIP='{}' AND positionID='{}'").format(ip,position)
    grabResult = dbSelect(sqlConn, grabSql)
    return grabResult[0][0]


def importMappingData(inputFile):
    with open(mapDataFile, newline='') as mapFile: #Loop through each line
        rawData = csv.DictReader(mapFile)
        for map in rawData:
            mapCloset = map['Closet']
            mapCurPanelID = map['CurPanelID']
            mapPanelPort = map['PanelPort']
            mapMapData = map['MapData']
            mapCurrentSwitchID = map['CurrentSwitchID']
            mapCurrenIntID = map['CurrentIntID']

            discoverySql = str("REPLACE INTO switchportMap(Closet, CurPanelID, PanelPort, MapData, CurrentSwitchID, CurrentInt) VALUES ('{}', '{}', '{}', '{}', '{}', '{}' );").format(mapCloset, mapCurPanelID, mapPanelPort, mapMapData, mapCurrentSwitchID,  mapCurrenIntID)
            #print(discoverySql)
            discoveryInsert = dbTableInsert(sqlConn, discoverySql)

def ClosetList(conn):
    closetSql = str("SELECT DISTINCT(closet) FROM switches;")
    closetResult = dbSelect(conn, closetSql)
    return closetResult

def NewStackCount(conn, ip):
    sql = str("SELECT COUNT(newSwitchIP) FROM switches WHERE newSwitchIP='{}'").format(ip)
    print(sql)
    result = dbSelect(conn,sql)
    return int(result[0][0])

def swlist(conn,closet):
    swsql = str("SELECT * FROM switches WHERE closet = '{}'").format(closet)
    swl = dbSelect(conn, swsql)
    return swl

#def PortDescription(conn,)

def updateSwitchStackData(conn):
    #Get unique list of switches based on new IP
    idfNewSwitchIPListSql = str("SELECT DISTINCT(newSwitchIP) FROM switches")
    idfNewSwitchIPList = dbSelect(sqlConn,idfNewSwitchIPListSql)
    for newIP in idfNewSwitchIPList:
        newIP = newIP[0]
        if newIP == "IGNORE":
            print("Ignoring switch update due to 'IGNORE'.")
        else:
            #Get list of switches based on new IP
            switchStackListSql = str("SELECT * FROM switches WHERE newSwitchIP = '{}' ORDER BY newSwitchPosition").format(newIP) #Was just "position"
            print(switchStackListSql)
            switchStackList = dbSelect(sqlConn, switchStackListSql)
            newStackID = switchStackList[0][9]
            #newStackID = newStackID[1:]
            UpdateMappingsSql = str("UPDATE switches SET newStackID='{}' WHERE newSwitchIP = '{}';").format(newStackID, newIP)
            UpdateMappings = dbTableInsert(sqlConn, UpdateMappingsSql)

#THis is NOT USED.. Stop Editing it!
"""
def MapDataToDiscovery(conn):
    #Get list of new SwitchIP's
    idfNewSwitchIPListSql = str("SELECT DISTINCT(newSwitchIP) FROM switches")
    idfNewSwitchIPList = dbSelect(conn,idfNewSwitchIPListSql)
    for nsIP in idfNewSwitchIPList:
        nsIP = nsIP[0]
        if nsIP == '':
            print("New IP is Empty.  Skipping")
            continue
        elif nsIP == 'IGNORE':
            print("Ignoring because new switch is set to 'IGNORE'.")
        else:
        #Time to get the interfaces
            newIPPortListSql = str("select * FROM switchportMap WHERE NewSwitchIP='{}'").format(nsIP)
            newIPPortList = dbSelect(conn, newIPPortListSql)
            print("NewIPPortListSQL: "+newIPPortListSql)
            for port in newIPPortList:
                crawlGrabSql = '' #Will populate depending on requirement
                currentIP = port[8]
                currentInt = port[9]
                currentSID = port[5] #CurrentSwitchID
                currentSSID = port[6] #CurrentSwitchStackID
                #Remove the S at the beginning
                currentSID = int(currentSID[1:])
                #currentSSID = int(currentSSID[1:])


                #intStackID = currentSID - currentSSID #SwitchStackID must be bigger for this to be valid....  hmm.


                if switchStackCheck(currentIP):
                    print("We gots a stack situation!")
                    print("Port: "+str(port))
                    portTypeGrabSql = str("SELECT intTypeID FROM portDiscovery WHERE ip='{}' and portID='{}' AND intTypeID != 'Te' AND portType != 'MOD' ").format(currentIP, currentInt)
                    portTypeGrab = dbSelect(conn, portTypeGrabSql)
                    print("Port Type SQL: "+portTypeGrabSql)
                    portTypeGrab = portTypeGrab[0][0]
                    #posCounter = intStackID + 1 #Used to increment when the intID chagnes based on the stack position (gi1..-> gi2...etc)

                    posCounter = GrabIntStackID(currentIP)
                    #print("Current Switch ID:"+str(currentSID))
                    #print("Current Stack ID:"+str(currentSSID))
                    #print("IntStack ID:"+str(intStackID))
                    intface = str("{}{}/0/{}").format(portTypeGrab,posCounter,currentInt)
                    crawlGrabSql = str("SELECT * FROM portDiscovery WHERE ip='{}' and interface='{}' AND intTypeID != 'Te' AND portType != 'MOD' ").format(currentIP, intface)
                else:
                    #pr int("They are the same.. Yay!")
                    crawlGrabSql = str("SELECT * FROM portDiscovery WHERE ip='{}' and portID='{}' AND intTypeID != 'Te' AND portType != 'MOD'").format(currentIP, currentInt)

                print(crawlGrabSql)
                #sys.exit()
                crawlGrabData = dbSelect(conn, crawlGrabSql)

                print("Source: "+str(port))
                print(crawlGrabData)
                print("==================================")
                #Update switchportMAP
                sqlUpdateRow = str("UPDATE switchportMap SET portDiscoveryID={} WHERE id={}").format(crawlGrabData[0][0], port[0])
                print(sqlUpdateRow)
                print("==================================")
                dbTableInsert(conn, sqlUpdateRow)


"""
def UpdateBuiltSwitch(conn,newSwitchIP):
    sql = str("UPDATE switches SET built='1' WHERE newSwitchIP='{}'").format(newSwitchIP)
    dbTableInsert(conn, sql)


##User Action:
while True:
    runTimeOption = input("Please make a selection:\r\n (1) Run Import\r\n (2) Map Data\r\n (3) Generate Config (Build)\r\n (4) Generate Config (Test)\r\n (5) Build All\r\n (6) Quit\r\n")
    if runTimeOption == "1":
        dbCheck()
        sqlConnStr = str("{}/{}").format(dbDir,dbFileName)
        sqlConnStr = os.path.normpath(sqlConnStr)
        sqlConn = db_conn(sqlConnStr)

        sqlDataTable = """ CREATE TABLE IF NOT EXISTS switchportMap (
            id integer PRIMARY KEY,
            Closet text NOT NULL,
            CurPanelID int,
            PanelPort int,
            MapData text,
            CurrentSwitchID text,
            CurrentSwitchStackID text,
            CurrentSwitchHostname text,
            CurrentSwitchIP text,
            CurrentInt text,
            NewPanelID text,
            NewSwitchHostname text,
            NewSwitchIP text,
            NewSwitchInt int,
            NewSwitchIntDescrip text,
            NewStackID int,
            portDiscoveryID int,
            UNIQUE (Closet, CurPanelID, PanelPort)
        ); """
        sqlSwitchesTable = """ CREATE TABLE IF NOT EXISTS switches (
            id integer PRIMARY KEY,
            closet text,
            currentSwitchName text,
            currentIP text,
            position int,
            positionID text,
            curStackID text,
            newSwitchName text,
            newSwitchIP text,
            newSwitchPosition int,
            newStackID int,
            username text,
            password text,
            newSubnetMask text,
            newDGW text,
            mgtVlan text,
            built int DEFAULT 0 NOT NULL,
            stackIntID int
        ); """

        sqlSwitchDiscoveryData = """ CREATE TABLE IF NOT EXISTS portDiscovery (
            id integer PRIMARY KEY,
            ip text NOT NULL,
            hostname text NOT NULL,
            interface text NOT NULL,
            intType text NOT NULL,
            intTypeID text NOT NULL,
            portType text NOT NULL,
            portID text NOT NULL,
            accessVlan text,
            voiceVlan text,
            nativeVlan text,
            allowedVlan text,
            pruningVlan text
        );

        """

        mactabledump = """ CREATE TABLE IF NOT EXISTS mactables (
            id integer PRIMARY KEY,
            switch test NOT NULL,
            vlan text NOT NULL,
            mac text NOT NULL,
            type text NOT NULL,
            port text NOT NULL
        )

        """

        arptabledump = """ CREATE TABLE IF NOT EXISTS arptables (
            id integer PRIMARY KEY,
            switch test NOT NULL,
            protocol text,
            address text,
            age text,
            mac text,
            type text,
            interface text
        )

        """


        dbTableSetup(sqlConn, sqlDataTable)
        dbTableSetup(sqlConn, sqlSwitchesTable)
        dbTableSetup(sqlConn, sqlSwitchDiscoveryData)
        dbTableSetup(sqlConn, mactabledump)
        dbTableSetup(sqlConn, arptabledump)


        while True:
            #Specify or enter a CSV file
            files = [f for f in os.listdir('.') if os.path.isfile(f)]
            for f in files:
                if f.endswith(".csv"):
                    inputFiles.append(f)

            print("Please select source CSV containing the switches:\r\n")
            c = 1
            for f in inputFiles:
                opt = str("{}: {}").format(c, f)
                print(opt)
                c+=1
            try:
                loginSelection = input("Selection: \r\n")
            except ValueError:
                print("Not a number.  Please try again")
                continue
            else:
                loginSelection = int(loginSelection) - 1
                if inputFiles[loginSelection]:
                    switchFile = inputFiles[loginSelection]
                    print(switchFile)
                    break
                else:
                    print(loginSelection)
                    print('Invalid selection.\r\n')


        ## Import Switches to DB
        importSwitches(switchFile)


        ##Get user input for login
        while True:
            loginSelection = input("Please make a selection:\r\n (1) Enter credentials\r\n (2) Read from DB (from CSV Import):\r\n")
            if loginSelection == "1":
                user = input("Username: ")
                pw = getpass.getpass()
                break
            elif loginSelection == "2":
                break
            else:
                print('Invalid selection.\r\n')


        #getSwitchSql = str("SELECT * FROM switches") #Original array values; 3,9,10
        getSwitchSql = str("SELECT DISTINCT currentIP, username, password FROM switches")
        getSwitchDB = dbSelect(sqlConn, getSwitchSql)

        for dbSwitch in getSwitchDB:
            switches[dbSwitch[0]] = {}
            switches[dbSwitch[0]]['CurrentSwitchIP'] = dbSwitch[0]
            switches[dbSwitch[0]]['user'] = dbSwitch[1]
            switches[dbSwitch[0]]['password'] = dbSwitch[2]

        #Work through CSV File...
        for switch in switches:
            #print(switch['host'])/len(switch['host'])
            host = switches[switch]['CurrentSwitchIP']


            if loginSelection == "2":
                user = switches[switch]['user']
                pw = switches[switch]['password']
            #Testing/Debug a switch that doesn't actually exist but can be in the CSV/DB.
            if user == "IGNORE":
                continue
                print("No Login; Skipping switch...")
            if host == "IGNORE":
                print("Skipping discovery due to 'IGNORE'.")
                continue

            configSend = "show interfaces description" #Actual configuration change we want to send
            configCommands = [configSend] #Put both together to send to Connection, can be an array so chain them together.

            #Tee up the connection object
            deviceConnect = {
                'device_type': 'cisco_ios',
                'ip': host,
                'username': user,
                'password': pw,
                'timeout': 10,
                'auth_timeout': 10
            }
            #Setup the connection handler
            msg = str("Connecting to device: {}").format(host)
            print(msg)
            logFile.write(msg+"\n")

            try:
                dev_connect = ConnectHandler(**deviceConnect)

            except (NetMikoTimeoutException, NetMikoAuthenticationException) as e:
                print(e)
                msg = str("Skipped due to timeout or authentication:").format(host)
                print(msg)
                logFile.write(msg+"\n")
                continue
            #If the connetion was good, work through the stuff.
            if dev_connect:

                msg = "Connection successful!"
                print(msg)
                logFile.write(msg+"\n")

                #Get hostname
                hostnameOutput = dev_connect.find_prompt()
                hostname=hostnameOutput.replace(">","")
                hostname=hostname.replace("#","")

                interfaceDict[hostname] = {}
                interfaceDict[hostname]['hostname'] = hostname

                dumpMacCmd = "show mac address-table"
                macTable = dev_connect.send_command(dumpMacCmd, use_textfsm=True)
                DumpMacTable(sqlConn, host, macTable)

                dumpArpCmd = "show ip arp"
                arpTable = dev_connect.send_command(dumpArpCmd, use_textfsm=True)
                DumpArpTable(sqlConn, host, arpTable)

                output = dev_connect.send_command(configSend, use_textfsm=True)
                msg = str("Sending the Commands...")
                print(msg)
                logFile.write(msg+"\n")
                if debug == 1:
                    pprint(output)
                    logFile.write("[OUTPUT]: \n "+pformat(output)+"\n")

                portCounter = 1
                for switchport in output:
                    interfaceData=''
                    interfaceType=''
                    accessVlan=''
                    VoiceVlan=''
                    nativeVlan=''
                    allowedVlan=''
                    pruningVlan=''
                    portType = ''
                    portID = ''
                    if str.startswith(switchport['port'],"V"):
                        msg = str("Interface {} is a VLAN. Skipping... ").format(switchport['port'])
                        print(msg)
                        logFile.write(msg+"\n")
                    else:
                        portStat = portCheck(switchport['port'])
                        intTypeID = switchport['port']
                        if str.endswith(switchport['port'],"/0"):
                            portType = "MGT"
                            portID = "MGT"

                        elif portStat:
                            ex = switchport['port'].split("/")
                            if len(ex) > 2:
                                #This is a larger switch
                                if not int(ex[1]) == 0:
                                    portType = "MOD"
                                    portID = ex[2]
                                    #portID = str(portCounter)
                                else:
                                    portType = "PHY"
                                    portID = ex[2]
                                    #portID = str(portCounter)
                            else:
                                #Only single interfaces like gi0/1
                                portType = "PHY"
                                PortID = ex[1]
                                #portID = str(portCounter)
                            portCounter+=1
                        elif not portStat:
                            if not intTypeID[:2] == "Fa":
                                portType = "VIRT"
                            else:
                                portType = "PHY"
                            portID = switchport['port']



                        ###New
                        cmd = str("show run int {}").format(switchport['port'])
                        intConf = dev_connect.send_command(cmd, use_textfsm=True)
                        if re.search("(.*)(mode)(\s)((access)|(trunk))((\\n)(.*))?",intConf,re.IGNORECASE):
                            modeSearch = re.search("(.*)(mode)(\s)((access)|(trunk))((\\n)(.*))?",intConf,re.IGNORECASE)
                            nomodeSearch = re.search("(.*)(no switchport)((\\n)(.*))?",intConf,re.IGNORECASE)
                            if modeSearch.group(5):
                                interfaceType='Access'
                                msg = str("Interface {} is an access port.").format(switchport['port'])
                                print(msg)
                                logFile.write(msg+"\n")
                                accVlanSearch = re.search("(.*)(access vlan)(\s)(\d+)((\\n)(.*))?",intConf,re.IGNORECASE)
                                vVlanSearch = re.search("(.*)(voice vlan)(\s)(\d+)",intConf,re.IGNORECASE)
                                if accVlanSearch:
                                    accessVlan=accVlanSearch.group(4)
                                    if vVlanSearch:
                                        VoiceVlan=vVlanSearch.group(4)

                            elif modeSearch.group(6):
                                interfaceType='Trunk'
                                msg = str("Interface {} is a trunk").format(switchport['port'])
                                print(msg)
                                logFile.write(msg+"\n")
                                nativeVlanSearch = re.search("(.*)(native vlan)(\s)(\d+)((\\n)(.*))?",intConf,re.IGNORECASE)
                                allowedVlanSearch = re.search("(.*)(allowed vlan)(\s)((\d+)((-)(\d+))?)((\\n)(.*))?",intConf,re.IGNORECASE)
                                pruningVlanSearch = re.search("(.*)(pruning vlan)(\s)((\d+)((-)(\d+))?)((\\n)(.*))?",intConf,re.IGNORECASE)
                                intConf = intConf.split("\n")
                                if len(intConf) >= 1:
                                    for vlan in intConf:
                                        if nativeVlanSearch:
                                            nativeVlan=nativeVlanSearch.group(4)
                                        if allowedVlanSearch:
                                            allowedVlan=allowedVlanSearch.group(4)
                                        if pruningVlanSearch:
                                            pruningVlan=pruningVlanSearch.group(4)

                        elif re.search("(.*)(no switchport)((\\n)(.*))?",intConf,re.IGNORECASE):
                                interfaceType = 'L3'
                                msg = str("Interface {} is a L3 port.").format(switchport['port'])
                                print(msg)
                                logFile.write(msg+"\n")
                        else: #If no output then its an 'access' by default.  Unless a VRF?
                            interfaceType = "Access"
                            msg = str("Interface {} has no specific command.  Operating as an Access port.").format(switchport['port'])
                            print(msg)

                        ###/New
                        #Write Data to DB:


                        interfaceDict[hostname]['ip'] = host
                        interfaceDict[hostname][switchport['port']] = {}
                        interfaceDict[hostname][switchport['port']]['intType'] = interfaceType
                        interfaceDict[hostname][switchport['port']]['accessVlan'] = accessVlan
                        interfaceDict[hostname][switchport['port']]['voiceVlan'] = VoiceVlan
                        interfaceDict[hostname][switchport['port']]['nativeVlan'] = nativeVlan
                        interfaceDict[hostname][switchport['port']]['allowedVlan'] = allowedVlan
                        interfaceDict[hostname][switchport['port']]['pruningVlan'] = pruningVlan


                        switchPortSql = str("INSERT INTO portDiscovery(hostname, ip, interface, intType, intTypeID, portType, portID, accessVlan, voiceVlan, nativeVlan, allowedVlan, pruningVlan) VALUES ('{}', '{}', '{}', '{}', '{}', '{}', '{}', '{}', '{}', '{}', '{}', '{}' ); ").format(hostname, host, switchport['port'], interfaceType, intTypeID[:2], portType, portID, accessVlan, VoiceVlan, nativeVlan, allowedVlan, pruningVlan)
                        dbPortData = dbTableInsert(sqlConn, switchPortSql)




                #Close connection and move on.
                msg = "Host finished.  Disconnecting..."
                print(msg)
                logFile.write(msg+"\n")
                dev_connect.disconnect()
        #sqlConn.close()
        continue
    elif runTimeOption == "2":
        ### BEGIN Select Update Files to uddate SWITCH DATA###
        while True:
            #Specify or enter a CSV file
            files = [f for f in os.listdir('.') if os.path.isfile(f)]
            for f in files:
                if f.endswith(".csv"):
                    inputFiles.append(f)
            print("Please select source CSV containing the new SWITCHES:\r\n")
            c = 1
            for f in inputFiles:
                opt = str("{}: {}").format(c, f)
                print(opt)
                c+=1
            try:
                loginSelection = input("Selection: \r\n")
            except ValueError:
                print("Not a number.  Please try again")
                continue
            else:
                loginSelection = int(loginSelection) - 1
                if inputFiles[loginSelection]:
                    inputFile = inputFiles[loginSelection]
                    print(inputFile)
                    break
                else:
                    print(loginSelection)
                    print('Invalid selection.\r\n')

        while True:
            #Specify or enter a CSV file
            inputFiles.clear()
            files.clear()
            files = [f for f in os.listdir('.') if os.path.isfile(f)]
            for f in files:
                if f.endswith(".csv"):
                    inputFiles.append(f)

            print("Please select source CSV containing the MAP DATA:\r\n")
            c = 1
            for f in inputFiles:
                opt = str("{}: {}").format(c, f)
                print(opt)
                c+=1
            try:
                loginSelection = input("Selection: \r\n")
            except ValueError:
                print("Not a number.  Please try again")
                continue
            else:
                loginSelection = int(loginSelection) - 1
                if inputFiles[loginSelection]:
                    mapDataFile = inputFiles[loginSelection]
                    print(inputFile)
                    break
                else:
                    print(loginSelection)
                    print('Invalid selection.\r\n')



        print("Switch File:"+inputFile)
        print("Mapping Data File:"+mapDataFile)


        #DB Connect
        sqlConnStr = str("{}/{}").format(dbDir,dbFileName)
        sqlConnStr = os.path.normpath(sqlConnStr)
        sqlConn = db_conn(sqlConnStr)

        #Work through CSV File...
        ###END Select Update Files to uddate SWITCH DATA###
        dbTableFlush(sqlConn,"switches")
        importSwitches(inputFile)
        updateSwitches(inputFile)
        CorrectStackInterfaceProblem()

        #Map stacking information in Switch Table
        updateSwitchStackData(sqlConn)

        ### BEGIN Select Update Files to MAP DISCOVERY ###
        importMappingData(mapDataFile)
        #Grab all closets
        closetSql = str("SELECT DISTINCT(closet) FROM switchportMap;")
        closetList = dbSelect(sqlConn, closetSql)
        for closet in closetList:
            closet = closet[0]
            #PortMap For Closet
            portMapDataSql = str("SELECT * FROM switchportMap WHERE Closet = '{}'").format(closet)
            portMapData = dbSelect(sqlConn,portMapDataSql)
            for portMap in portMapData:
                #print(portMap)
                rowID = portMap[0]
                oldSwitchID = portMap[5]
                panelID = portMap[2] #The Panel ID
                pID = panelID[1:] #PanelID without the "P"
                panelPort = portMap[3] #Panel Port
                oldSwitchPort = portMap[9]

                #New switchport map
                panelPort = int(panelPort)

                if panelPort < 25:
                    newSwitchPort = panelPort + (panelPort - 1)
                elif panelPort > 24:
                    newSwitchPort = 2*(panelPort-24)

                portDescription = str("{} -> {}").format(panelID, panelPort)


                #Select the OLD switch for the current map data
                oldSwitchSelectSql = str("SELECT * FROM switches WHERE positionID='{}' AND closet = '{}'").format(oldSwitchID,closet)
                oldSwitchSelect = dbSelect(sqlConn,oldSwitchSelectSql)

                if oldSwitchSelect:
                    #print("Data found!")
                    #print(oldSwitchSelect)

                    currentSwitchName = oldSwitchSelect[0][2]
                    oldSwitchIP = oldSwitchSelect[0][3]
                    currentStackID = oldSwitchSelect[0][6]



                    #print(oldSwitchIP)
                    #Check to see if this is a stack
                    portDiscoveryDataSql = ''
                    currentPositionID = oldSwitchSelect[0][5]
                    currentStackID = oldSwitchSelect[0][6]
                    currentPositionID = int(currentPositionID[1:])
                    #currentStackID = int(currentStackID[1:])
                    currentStackID = int(currentStackID[1:])
                    #intPosition = (currentPositionID - currentStackID) + 1 #Exampls (5 - 2) + 1 = 4 => Becomes gi4/X/X
                    intPosition = GrabIntStackID(oldSwitchIP,oldSwitchID)

                    if oldSwitchIP == "IGNORE":
                        #We still need to map the Patch Panel to a default value.
                        #print(str("Special Processing due to 'IGNORE' on old switch...").format(portMap))

                        #Grab the switch information for the NEW switch.
                        newSwitchSql = str("SELECT * FROM switches WHERE Closet = '{}' AND NewSwitchPosition = '{}' AND newSwitchName IS NOT 'IGNORE' ").format(closet, pID)
                        newSwitch = dbSelect(sqlConn, newSwitchSql)
                        if newSwitch:
                            #print(newSwitchSql)
                            #print(newSwitch)
                            newSwitchIP = newSwitch[0][8]
                            newStackSql = str("SELECT * FROM switches where newSwitchIP = '{}' ORDER BY NewSwitchPosition").format(newSwitchIP)
                            newstackResult = dbSelect(sqlConn, newStackSql)
                            newStackID = newstackResult[0][9]
                            #newStackID = newStackID[1:]

                        #THis is most likely something we flat out do not care about but need to keep the mapping data for the panel.  The switch wont build?
                        else:
                            continue
                        updateMappingsSql = str("UPDATE switchportMap SET NewPanelID='{}', NewSwitchHostname='{}', NewSwitchIP='{}', NewStackID='{}', NewSwitchInt='{}', NewSwitchIntDescrip='{}', portDiscoveryID={} WHERE id = {};").format(panelID, newSwitch[0][7], newSwitchIP, newStackID, newSwitchPort, portDescription, portDiscoverID, rowID)
                        #print(updateMappingsSql)
                        dbTableInsert(sqlConn,updateMappingsSql)
                        continue


                    #Run the Query to get the discovery ID for VLAN's
                    #Check to see if this is a Stack
                    if switchStackCheck(oldSwitchIP):
                        print("This is a stack")
                        intface = str("Gi{}/0/{}").format(intPosition,oldSwitchPort)
                        intface2 = str("Gi{}/{}").format(intPosition,oldSwitchPort) #Things like 6905... Painful.
                        portDiscoveryDataSql = str("SELECT * FROM portDiscovery WHERE ip='{}' AND (interface='{}' OR interface='{}')").format(oldSwitchIP,intface,intface2)
                        print(portDiscoveryDataSql)
                        #if closet=="EC032":
                            #print("Current PositionID:"+str(currentPositionID))
                            #print("Current Stack ID:"+str(currentStackID))
                            #print(portMap)
                            #print(portDiscoveryDataSql)

                    #Not a stack, only a single switch
                    else:
                        #print("Non Stack switch")
                        portDiscoveryDataSql = str("SELECT * FROM portDiscovery WHERE ip='{}' AND portID='{}'").format(oldSwitchIP,oldSwitchPort)

                    #print(portDiscoveryDataSql)
                    portDiscoveryData = dbSelect(sqlConn,portDiscoveryDataSql)
                    #print(portDiscoveryData)

                    portDiscoverID=0
                    #Check to see if these is discovery data to match the mapping
                    if portDiscoveryData:
                        #If data is found, grab the DB ID
                        portDiscoverID = portDiscoveryData[0][0]

                    else:
                        print("No discovery data for port: "+portDiscoveryDataSql)


                    #Grab the switch information for the current switch.
                    newSwitchSql = str("SELECT * FROM switches WHERE Closet = '{}' AND NewSwitchPosition = '{}' AND newSwitchName IS NOT 'IGNORE' ").format(closet, pID)
                    newSwitch = dbSelect(sqlConn, newSwitchSql)

                    #print("Switch Position SQL: "+newSwitchSql)
                    if not newSwitch:
                        print("Failed to find the new switch. SQL: "+newSwitchSql)
                        continue
                    else:
                        newSwitch = newSwitch[0]

                    #portDescription = str("{} -> {}").format(panelID, panelPort)
                    newSwitchIP = newSwitch[8]
                    newStackSql = str("SELECT * FROM switches where newSwitchIP = '{}' ORDER BY newSwitchPosition").format(newSwitchIP)

                    newstackResult = dbSelect(sqlConn, newStackSql)
                    newStackID = newstackResult[0][9]
                    #newStackID = newStackID[1:]

                    updateMappingsSql = str("UPDATE switchportMap SET CurrentSwitchHostname='{}', CurrentSwitchIP='{}', CurrentSwitchStackID='{}', NewPanelID='{}', NewSwitchHostname='{}', NewSwitchIP='{}', NewStackID='{}', NewSwitchInt='{}', NewSwitchIntDescrip='{}', portDiscoveryID={} WHERE id = {};").format(currentSwitchName, oldSwitchIP, currentStackID, panelID, newSwitch[7], newSwitchIP, newStackID, newSwitchPort, portDescription, portDiscoverID, rowID)
                    dbTableInsert(sqlConn,updateMappingsSql)

                    if oldSwitchIP == '172.21.252.252':
                        print(updateMappingsSql)

                    #sys.exit()


                #The port was labled as Empty so we need to map without any data.
                else:
                    print("No data found! Use Defaults.")
                    #print(portMap)
                    #print(oldSwitchSelectSql)

                    #Grab the switch information for the current switch.
                    newSwitchSql = str("SELECT * FROM switches WHERE Closet = '{}' AND NewSwitchPosition = '{}' AND newSwitchName IS NOT 'IGNORE' ").format(closet, pID)
                    newSwitch = dbSelect(sqlConn, newSwitchSql)
                    #print(newSwitchSql)

                    #Double check to make sure we found a new switch
                    if not newSwitch:
                        print("Failed to find the new switch. SQL: "+newSwitchSql)
                        continue
                    else:
                        newSwitch = newSwitch[0]

                    #portDescription = str("{} -> {}").format(panelID, panelPort)
                    newSwitchIP = newSwitch[8]
                    newStackSql = str("SELECT * FROM switches where newSwitchIP = '{}' ORDER BY newSwitchPosition").format(newSwitchIP)

                    newstackResult = dbSelect(sqlConn, newStackSql)
                    newStackID = newstackResult[0][9]
                    #newStackID = newStackID[1:]


                    updateMappingsSql = str("UPDATE switchportMap SET NewPanelID='{}', NewSwitchHostname='{}', NewSwitchIP='{}', NewStackID='{}', NewSwitchInt='{}', NewSwitchIntDescrip='{}' WHERE id = {};").format(panelID, newSwitch[7], newSwitchIP, newStackID, newSwitchPort, portDescription, rowID)
                    dbTableInsert(sqlConn,updateMappingsSql)
                    #print(updateMappingsSql)
                    #sys.exit()

        cleanup(sqlConn)
        continue
    elif runTimeOption == "3" or runTimeOption == "4":

        #po = serial.tools.list_ports.comports()
        #print(po[2])

        if runTimeOption == "3":
            #Actual prepare the build run.  Otherwise we are just testing.
            serialPort = serial_ports()
            print("Selected: "+serialPort)

        runTime3 = True
        while runTime3:
            sqlConnStr = str("{}/{}").format(dbDir,dbFileName)
            sqlConnStr = os.path.normpath(sqlConnStr)
            sqlConn = db_conn(sqlConnStr)

            #print("This option is not ready yet.  Please try again.")
            cllist = ClosetList(sqlConn)
            cllist = list(cllist)#Count the number of closets for printing options
            n=0 #Option output counter
            print("Please select the source closet:")
            for cl in cllist:
                cl = cl[0]
                n+=1
                #closets.append(cl[0])
                print(str(n)+": "+cl)
            print("\r")
            try:
                closetSelection = input("Selection: \r\n") #Take input from user
                closetSelection = int(closetSelection) - 1 #Convert input to int and subtract one to match Array index

                #print(cllist[closetSelection])
                #swlistPrint = swlist(sqlConn, cllist[closetSelection]) #Using the function
                idfNewSwitchIPListSql = str("SELECT DISTINCT(newSwitchIP) FROM switches WHERE closet = '{}' AND newswitchIP != 'IGNORE' AND built = 0").format(cllist[closetSelection][0])
                print(idfNewSwitchIPListSql)
                idfNewSwitchIPList = dbSelect(sqlConn,idfNewSwitchIPListSql)


            except (ValueError,IndexError):
                print("Not an option.  Please try again\r\n")
                continue
            else:
                idfLoop = True #Set to breakout of this loop and reselect based on switches being built.
                while idfLoop:
                    sc = 0
                    print("\r\n")
                    selectedSwitch = '' #Set to use for updating after build
                    for nsIP in idfNewSwitchIPList:
                        sc+=1
                        nsIP = nsIP[0]
                        switchBuildOpt = []
                        idfOldSwitchListSql = str("SELECT * FROM switches WHERE newSwitchIP = '{}' AND built = 0 ORDER BY positionID").format(nsIP)
                        idfOldSwitchList = dbSelect(sqlConn, idfOldSwitchListSql)
                        #print(idfOldSwitchList)
                        print("Option: "+str(sc))
                        print("=======================================")
                        print("----New Switch Master: "+nsIP+"----")
                        print("---------------------------------------")
                        print("Contains (old):")
                        for oldSwitch in idfOldSwitchList:
                            print(oldSwitch[2]+": "+oldSwitch[3])
                        print("=======================================\r\n")
                    try:
                        switchSelection = input("Selection: ") #Take input from user
                        switchSelection = int(switchSelection) - 1 #Convert input to int and subtract one to match Array index
                    except (ValueError,IndexError):
                        print("Not an option.  Please try again")
                        continue
                    else:
                        configSend = []
                        confgCmd = "configure terminal"
                        configWrite = "write mem"
                        endCfg = "end"
                        exitCfg = "exit"

                        #Everything is good, lets begin building
                        newSwitchSelect = idfNewSwitchIPList[switchSelection][0]
                        selectedSwitch = newSwitchSelect
                        print("You Selected: "+str(newSwitchSelect))
                        idfOldSwitchSelectSql = str("SELECT * FROM switches WHERE newSwitchIP = '{}' AND built = 0 ORDER BY positionID").format(newSwitchSelect)
                        idfOldSwitchSelect = dbSelect(sqlConn, idfOldSwitchSelectSql)
                        #This is where all the new commands will go
                        hostname = idfOldSwitchSelect[0][7]
                        newIP = idfOldSwitchSelect[0][8]
                        newDGW = idfOldSwitchSelect[0][14]
                        newMask = idfOldSwitchSelect[0][13]
                        mgtVlan = idfOldSwitchSelect[0][15]
                        newHost = str("hostname {}").format(hostname) #This will always be a constant of the new Hostname

                        #Reformat Hostname
                        hostnamere = re.search(r'(\-\d)$',hostname)
                        if hostnamere:
                            hostname = hostname[:-2]

                        snmpLocation = hostname.split("-")
                        snmpLocation = snmpLocation[0]

                        #Configs
                        #mgtVlan1 = str("int vlan {}").format(mgtVlan)

                        configSend.append(str(confgCmd))
                        configSend.append(str("no logging console"))
                        configSend.append(str("no service pad"))
                        configSend.append(str("service tcp-keepalives-in"))
                        configSend.append(str("service tcp-keepalives-out"))
                        configSend.append(str("service timestamps debug datetime localtime"))
                        configSend.append(str("service timestamps log datetime localtime"))
                        configSend.append(str("service password-encryption"))
                        #######

                        configSend.append(str("hostname {}").format(hostname))

                        configSend.append(str("boot-start-marker"))
                        configSend.append(str("boot-end-marker"))
                        configSend.append(str("logging buffered 32768"))
                        configSend.append(str("logging persistent"))
                        configSend.append(str("redundancy"))
                        configSend.append(str("mode sso"))
                        configSend.append(str("end"))
                        configSend.append(str("config t"))
                        configSend.append(str("clock timezone EST -5 0"))
                        configSend.append(str("clock summer-time DST recurring"))
                        configSend.append(str("system mtu 9001"))


                        configSend.append(str("ip domain-name {}").format(domain))

                        configSend.append(str("ip name-server 127.0.0.1"))

                        configSend.append(str("vtp mode off"))
                        configSend.append(str("udld enable"))

                        configSend.append(str("crypto key gen rsa gen mod 4096"))

                        configSend.append(str("spanning-tree mode rapid-pvst"))
                        configSend.append(str("spanning-tree portfast default"))
                        configSend.append(str("spanning-tree portfast bpduguard default"))
                        configSend.append(str("spanning-tree extend system-id"))

                        configSend.append(str("errdisable recovery cause all"))
                        configSend.append(str("errdisable recovery interval 600"))


                        configSend.append(str("int vlan {}").format(mgtVlan))
                        configSend.append(str("ip address {} {}").format(newIP, newMask))
                        configSend.append(str("ip default-gateway {}").format(newDGW))
                        configSend.append(str("ip classless"))
                        configSend.append(str("ip http server"))
                        configSend.append(str("ip http secure-server"))
                        configSend.append(str("ip http access-class ipv4 22"))
                        configSend.append(str("ip http authentication local"))
                        configSend.append(str("ip http secure-server"))
                        configSend.append(str("logging facility syslog"))
                        configSend.append(str("logging host 127.0.0.1"))

                        #configSend.append(str("exit"))

                        #SNMP
                        #configSend.append(str("snmp-server enable traps"))
                        #configSend.append(str("snmp-server host 127.0.0.1 private"))
                        #configSend.append(str("snmp-server location {}").format(snmpLocation))
                        #configSend.append(str("snmp-server user orion-snmp SnmpNoAuthNoPrivGroup v3"))
                        #configSend.append(str("snmp-server group orion-npm v3 priv context orion-npm read orion-npm_ro write orion-npm_wr"))
                        #configSend.append(str("snmp-server group SnmpAuthPrivGroup v3 priv"))
                        #configSend.append(str("snmp-server group SnmpAuthNoPrivGroup v3 auth"))
                        #configSend.append(str("snmp-server group SnmpNoAuthNoPrivGroup v3 noauth"))
                        #configSend.append(str("snmp-server view orion-npm iso included"))
                        #configSend.append(str("snmp-server view orion-npm_ro iso included"))
                        #configSend.append(str("snmp-server view orion-npm_wr iso included"))
                        #configSend.append(str("snmp-server contact anemail@mycompany.com"))
                        #configSend.append(str("snmp-server enable traps"))
                        #configSend.append(str("snmp-server host 127.0.0.1 version 3 noauth orion-npm"))

                        #TACACS
                        #configSend.append(str("tacacs-server host 127.0.0.1"))
                        #configSend.append(str("tacacs-server directed-request"))
                        #configSend.append(str("tacacs-server key 7 1234567890"))
                        #configSend.append(str("ntp server 127.0.0.1 prefer"))

                        #Login Banner!







                        #configSend.append(str("crypto key generate rsa")) #Can remove if not needed
                        configSend.append(endCfg)
                        #configSend.append(str("write mem"))
                        configSend.append(confgCmd)

                        #Set Defaults for EVERYTHING
                        stackCount = NewStackCount(sqlConn,newIP)
                        count = 1

                        #while count <= stackCount:
                            #configSend.append(str("int range gi{}/0/1 - 48").format(count))
                            #configSend.append(str("switchport mode access"))
                            #configSend.append(str("switchport access vlan {}").format(defaultAccessVLAN))
                            #configSend.append(str(""))
                        #    count +=1


                        #Time to get the interfaces
                        #newIPPortListSql = str("SELECT * FROM switchportMap INNER JOIN portDiscovery ON switchportMap.portDiscoveryID=portDiscovery.id WHERE switchportMap.NewSwitchIP='{}' ORDER BY NewSwitchInt").format(newIP)
                        newIPPortListSql = str("SELECT * FROM switchportMap WHERE NewSwitchIP='{}' ORDER BY CurPanelID, NewSwitchInt").format(newIP)
                        newIPPortList = dbSelect(sqlConn, newIPPortListSql) #Lists all the interfaces that have mapping data.

                        intconf = []
                        recordCount = len(newIPPortList)

                        for port in newIPPortList:

                            print(port)
                            panelID = port[10]
                            newStackID = port[15]
                            switchInt = port[13]
                            intDescription = port[14]

                            if not port[16]:
                                print("No mapping found. Use defualts.")

                                switchIntType = "Access"
                                accessVlan = defaultAccessVLAN

                                panelID = panelID[1:]
                                #newStackID = newStackID[1:] #Removed S at some point.  Delete.
                                intStackID = int(panelID) - int(newStackID)
                                intStackID+=1 #Regards of position, it will always be +1 over the difference of the positions
                                intface = str("gi{}/0/{}").format(intStackID,switchInt)
                                intconf.append(str("int {}").format(intface))
                                intconf.append(str("description {}").format(intDescription))
                                intconf.append(str("switchport mode access"))
                                intconf.append(str("switchport access vlan {}").format(defaultAccessVLAN))
                                intconf.append(str("switchport nonegotiate"))
                                intconf.append(str("storm-control broadcast level 2"))
                                intconf.append(str("storm-control action shutdown"))
                                intconf.append(str("spanning-tree portfast"))
                                intconf.append(str("spanning-tree bpduguard enable"))
                                intconf.append(str("ip arp inspection limit rate 15"))

                            else:
                                print("Map data found. Using data.")
                                vlanSqlStr = str("SELECT * FROM portDiscovery WHERE id='{}'").format(port[16])
                                print(vlanSqlStr)
                                vlanSql = dbSelect(sqlConn, vlanSqlStr)
                                vlanSql = vlanSql[0]
                                print(vlanSql)

                                #switchIntType = port[21]
                                #accessVlan = port[25]
                                #VoiceVlan = port[26]
                                #nativeVlan = port[27]
                                #allowedVlan = port[28]
                                #allowedVlan = allowedVlan.strip('\"') #Multiple VLAN's are stored with "" in DB so must be removed.
                                #pruningVlan = port[29]

                                switchIntType = vlanSql[4]
                                accessVlan = vlanSql[8]
                                VoiceVlan = vlanSql[9]
                                nativeVlan = vlanSql[10]
                                allowedVlan = vlanSql[11]
                                if allowedVlan:
                                    if allowedVlan.find('\"'):
                                        allowedVlan = allowedVlan.strip('\"') #Multiple VLAN's are stored with "" in DB so must be removed.
                                pruningVlan = vlanSql[12]


                                #Remove the P & S at the beginning (respectivly)
                                panelID = panelID[1:]
                                #newStackID = newStackID[1:] #No need to remove S anymore.  Delete.
                                intStackID = int(panelID) - int(newStackID)
                                intStackID+=1 #Regards of position, it will always be +1 over the difference of the positions
                                intface = str("gi{}/0/{}").format(intStackID,switchInt)
                                intconf.append(str("int {}").format(intface))
                                intconf.append(str("description {}").format(intDescription))

                                if switchIntType == "Access":
                                    intconf.append(str("switchport mode {}").format(switchIntType))
                                    intconf.append(str("switchport nonegotiate"))
                                    intconf.append(str("storm-control broadcast level 2"))
                                    intconf.append(str("storm-control action shutdown"))
                                    intconf.append(str("spanning-tree portfast"))
                                    intconf.append(str("spanning-tree bpduguard enable"))
                                    intconf.append(str("ip arp inspection limit rate 15"))
                                    if accessVlan:
                                        #print("Access Vlan!")
                                        intconf.append(str("switchport access vlan {}").format(accessVlan))
                                        if VoiceVlan:
                                            #print("Voice Vlan!")
                                            intconf.append(str("switchport voice vlan {}").format(VoiceVlan))
                                        else:
                                            print("No Voice VLAN!")
                                        intconf.append(str("switchport port-security"))
                                        intconf.append(str("switchport port-security maximum 1"))
                                        intconf.append(str("switchport port-security aging time 10"))
                                        intconf.append(str("switchport port-security mac-address sticky"))
                                        intconf.append(str("spanning-tree guard root"))
                                        intconf.append(str("ip arp inspection limit rate 100"))
                                        intconf.append(str("auto qos trust dscp"))
                                    else:
                                        #May need to add a default if it doesn't have one.
                                        #print("No Access VLAN! Setting default.")
                                        intconf.append(str("switchport access vlan {}").format(defaultAccessVLAN))



                                elif switchIntType == "Trunk":
                                    intconf.append(str("no switchport access vlan {}").format(defaultAccessVLAN))
                                    intconf.append(str("switchport mode {}").format(switchIntType))

                                    if nativeVlan:
                                        intconf.append(str("switchport trunk native vlan {}").format(nativeVlan))
                                    if allowedVlan:
                                        intconf.append(str("switchport trunk allowed vlan {}").format(allowedVlan))
                                    if pruningVlan:
                                        intconf.append(str("switchport trunk allowed vlan {}").format(pruningVlan))
                                    intconf.append(str("switchport nonegotiate"))
                                    intconf.append(str("auto qos trust dscp"))

                                elif switchIntType == "L3":
                                    intconf.append(str("no switchport"))
                                else:
                                    #print("No mode was set.  Applying the 'default'.")
                                    #Need to add some defaults.
                                    intconf.append(str("switchport mode access"))
                                    intconf.append(str("switchport access vlan {}").format(defaultAccessVLAN))
                                #print(intconf)




                        intconf.append(str(endCfg))
                        #intconf.appent(str(configWrite)) #Uncomment to save as part of runtime
                        configSend.extend(intconf)

                        #console access
                        configSend.append(confgCmd)
                        configSend.append(str("logging console"))
                        configSend.append(str("line con 0"))
                        configSend.append(str("logging synchronous"))
                        configSend.append(str("exec-timeout 30 0"))
                        configSend.append(str("stopbits 1"))
                        configSend.append(str("line vty 0 4"))
                        configSend.append(str("access-class 22 in"))
                        configSend.append(str("logging synchronous"))
                        configSend.append(str("exec-timeout 30 0"))
                        configSend.append(str("transport preferred ssh"))
                        configSend.append(str("transport input ssh"))
                        configSend.append(str("transport output ssh"))
                        configSend.append(str("line vty 5 15"))
                        configSend.append(str("access-class 22 in"))
                        configSend.append(str("logging synchronous"))
                        configSend.append(str("exec-timeout 30 0"))
                        configSend.append(str("transport preferred ssh"))
                        configSend.append(str("transport input ssh"))
                        configSend.append(str("transport output ssh"))
                        configSend.append(str(endCfg))
                        configSend.append(confgCmd)
                        #configSend.append(str("enable secret 5 ABCDEFG"))
                        #configSend.append(str("username root privilege 15 secret 5 ABCDEFG"))
                        #configSend.append(str("username ausername privilege 15 secret apassword"))
                        configSend.append(str("aaa new-model"))
                        configSend.append(str("aaa authentication login default group tacacs+ local-case enable"))
                        configSend.append(str("aaa authorization console"))
                        configSend.append(str("aaa authorization exec default group tacacs+ local if-authenticated"))
                        configSend.append(str("aaa accounting exec default start-stop group tacacs+"))
                        configSend.append(str("aaa accounting commands 1 default start-stop group tacacs+"))
                        configSend.append(str("aaa accounting commands 15 default start-stop group tacacs+"))
                        configSend.append(str("aaa accounting network default start-stop group tacacs+"))
                        configSend.append(str("aaa accounting connection default start-stop group tacacs+"))
                        configSend.append(str("aaa accounting system default start-stop group tacacs+"))
                        configSend.append(str("aaa session-id common"))
                        configSend.append(str("aaa authorization commands 1 default group tacacs+ if-authenticated"))
                        configSend.append(str("aaa authorization commands 15 default group tacacs+ if-authenticated"))
                        configSend.append(str("aaa authentication webauth default group tacacs+ local enable"))
                        configSend.append(str(exitCfg))

                        #Config Build Complete.  Print to verify
                        print("Sending Config: ")
                        pprint(configSend)


                    if(runTimeOption == "3"):
                        nPushConfigSerial(serialPort,consoleUsername,consolePassword,configSend)
                        #UpdateBuiltSwitch(sqlConn, selectedSwitch)
                    idfLoop = False


        continue
    elif(runTimeOption == "5"):
        sqlConnStr = str("{}/{}").format(dbDir,dbFileName)
        sqlConnStr = os.path.normpath(sqlConnStr)
        sqlConn = db_conn(sqlConnStr)

        #print("This option is not ready yet.  Please try again.")
        cllist = ClosetList(sqlConn)
        for closet in cllist:
            closet = closet[0]
            idfNewSwitchIPListSql = str("SELECT DISTINCT(newSwitchIP) FROM switches WHERE closet = '{}' AND newswitchIP != 'IGNORE' AND built = 0").format(closet)
            #print(idfNewSwitchIPListSql)
            idfNewSwitchIPList = dbSelect(sqlConn,idfNewSwitchIPListSql)
            #print("Closet: "+closet)
            #print("New Closet IP's:")
            #print(idfNewSwitchIPList)
            for nsIP in idfNewSwitchIPList:
                nsIP = nsIP[0]
                switchBuildOpt = []
                configSend = []
                confgCmd = "configure terminal"
                configWrite = "write mem"
                endCfg = "end"
                exitCfg = "exit"
                #Everything is good, lets begin building
                newSwitchSelect = nsIP
                selectedSwitch = newSwitchSelect
                idfOldSwitchSelectSql = str("SELECT * FROM switches WHERE newSwitchIP = '{}' AND built = 0 ORDER BY positionID").format(newSwitchSelect)
                idfOldSwitchSelect = dbSelect(sqlConn, idfOldSwitchSelectSql)
                #This is where all the new commands will go
                hostname = idfOldSwitchSelect[0][7]
                newIP = idfOldSwitchSelect[0][8]
                newDGW = idfOldSwitchSelect[0][14]
                newMask = idfOldSwitchSelect[0][13]
                mgtVlan = idfOldSwitchSelect[0][15]
                newHost = str("hostname {}").format(hostname) #This will always be a constant of the new Hostname

                #Reformat Hostname
                hostnamere = re.search(r'(\-\d)$',hostname)
                if hostnamere:
                    hostname = hostname[:-2]

                snmpLocation = hostname.split("-")
                snmpLocation = snmpLocation[0]

                #Configs
                #mgtVlan1 = str("int vlan {}").format(mgtVlan)

                #configSend.append(str(confgCmd))
                configSend.append(str("no logging console"))
                configSend.append(str("no service pad"))
                configSend.append(str("service tcp-keepalives-in"))
                configSend.append(str("service tcp-keepalives-out"))
                configSend.append(str("service timestamps debug datetime localtime"))
                configSend.append(str("service timestamps log datetime localtime"))
                configSend.append(str("service password-encryption"))
                #######

                configSend.append(str("hostname {}").format(hostname))

                configSend.append(str("boot-start-marker"))
                configSend.append(str("boot-end-marker"))
                configSend.append(str("logging buffered 32768"))
                configSend.append(str("logging persistent"))
                configSend.append(str("redundancy"))
                configSend.append(str(" mode sso"))
                #configSend.append(str("end"))
                #configSend.append(str("config t"))
                configSend.append(str("clock timezone EST -5 0"))
                configSend.append(str("clock summer-time DST recurring"))
                configSend.append(str("system mtu 9001"))


                configSend.append(str("ip domain-name {}").format(domain))

                configSend.append(str("ip name-server 127.0.0.1"))
                configSend.append(str("vtp mode off"))
                configSend.append(str("udld enable"))

                configSend.append(str("crypto key gen rsa gen mod 4096"))

                configSend.append(str("spanning-tree mode rapid-pvst"))
                configSend.append(str("spanning-tree portfast default"))
                configSend.append(str("spanning-tree portfast bpduguard default"))
                configSend.append(str("spanning-tree extend system-id"))


                configSend.append(str("errdisable recovery cause all"))
                configSend.append(str("errdisable recovery interval 600"))


                configSend.append(str("int vlan {}").format(mgtVlan))
                configSend.append(str(" ip address {} {}").format(newIP, newMask))
                configSend.append(str(" ip default-gateway {}").format(newDGW))
                configSend.append(str("ip classless"))
                configSend.append(str("ip http server"))
                configSend.append(str("ip http secure-server"))
                configSend.append(str("ip http access-class ipv4 22"))
                configSend.append(str("ip http authentication local"))
                configSend.append(str("ip http secure-server"))
                configSend.append(str("logging facility syslog"))
                configSend.append(str("logging host 205.133.0.80"))

                #ACL
                configSend.append(str("access-list 22 permit 127.0.0.1"))
                #configSend.append(str("exit"))

                #SNMP
                configSend.append(str("snmp-server enable traps"))
                configSend.append(str("snmp-server host 127.0.0.1 private"))
                configSend.append(str("snmp-server location {}").format(snmpLocation))
                configSend.append(str("snmp-server user orion-snmp SnmpNoAuthNoPrivGroup v3"))
                configSend.append(str("snmp-server group orion-npm v3 priv context orion-npm read orion-npm_ro write orion-npm_wr"))
                configSend.append(str("snmp-server group SnmpAuthPrivGroup v3 priv"))
                configSend.append(str("snmp-server group SnmpAuthNoPrivGroup v3 auth"))
                configSend.append(str("snmp-server group SnmpNoAuthNoPrivGroup v3 noauth"))
                configSend.append(str("snmp-server view orion-npm iso included"))
                configSend.append(str("snmp-server view orion-npm_ro iso included"))
                configSend.append(str("snmp-server view orion-npm_wr iso included"))
                configSend.append(str("snmp-server contact anemail@mycompany.com"))
                configSend.append(str("snmp-server enable traps"))
                configSend.append(str("snmp-server host 127.0.0.1 version 3 noauth orion-npm"))

                #TACACS
                configSend.append(str("tacacs-server host 127.0.0.1"))
                configSend.append(str("tacacs-server directed-request"))
                configSend.append(str("tacacs-server key 7 1234567890"))
                configSend.append(str("ntp server 127.0.0.1 prefer"))

                #Login Banner!







                #configSend.append(str("crypto key generate rsa")) #Can remove if not needed
                #configSend.append(endCfg)
                #configSend.append(str("write mem"))
                #configSend.append(confgCmd)

                #Set Defaults for EVERYTHING
                stackCount = NewStackCount(sqlConn,newIP)
                count = 1

                #while count <= stackCount:
                    #configSend.append(str("int range gi{}/0/1 - 48").format(count))
                    #configSend.append(str("switchport mode access"))
                    #configSend.append(str("switchport access vlan {}").format(defaultAccessVLAN))
                    #configSend.append(str(""))
                #    count +=1


                #Time to get the interfaces
                #newIPPortListSql = str("SELECT * FROM switchportMap INNER JOIN portDiscovery ON switchportMap.portDiscoveryID=portDiscovery.id WHERE switchportMap.NewSwitchIP='{}' ORDER BY NewSwitchInt").format(newIP)
                newIPPortListSql = str("SELECT * FROM switchportMap WHERE NewSwitchIP='{}' ORDER BY CurPanelID, NewSwitchInt").format(newIP)
                newIPPortList = dbSelect(sqlConn, newIPPortListSql) #Lists all the interfaces that have mapping data.

                intconf = []
                recordCount = len(newIPPortList)

                for port in newIPPortList:

                    #print(port)
                    panelID = port[10]
                    newStackID = port[15]
                    switchInt = port[13]
                    intDescription = port[14]

                    if not port[16]:
                        #print("No mapping found. Use defualts.")

                        switchIntType = "Access"
                        accessVlan = defaultAccessVLAN

                        panelID = panelID[1:]
                        #newStackID = newStackID[1:] #Delete.
                        intStackID = int(panelID) - int(newStackID)
                        intStackID+=1 #Regards of position, it will always be +1 over the difference of the positions
                        intface = str("gi{}/0/{}").format(intStackID,switchInt)
                        intconf.append(str("int {}").format(intface))
                        intconf.append(str(" description {}").format(intDescription))
                        intconf.append(str(" switchport mode access"))
                        intconf.append(str(" switchport access vlan {}").format(defaultAccessVLAN))
                        intconf.append(str(" switchport nonegotiate"))
                        intconf.append(str(" storm-control broadcast level 2"))
                        intconf.append(str(" storm-control action shutdown"))
                        intconf.append(str(" spanning-tree portfast"))
                        intconf.append(str(" spanning-tree bpduguard enable"))
                        intconf.append(str(" ip arp inspection limit rate 15"))

                    else:
                        #print("Map data found. Using data.")
                        vlanSqlStr = str("SELECT * FROM portDiscovery WHERE id='{}'").format(port[16])
                        #print(vlanSqlStr)
                        vlanSql = dbSelect(sqlConn, vlanSqlStr)
                        vlanSql = vlanSql[0]
                        #print(vlanSql)

                        #switchIntType = port[21]
                        #accessVlan = port[25]
                        #VoiceVlan = port[26]
                        #nativeVlan = port[27]
                        #allowedVlan = port[28]
                        #allowedVlan = allowedVlan.strip('\"') #Multiple VLAN's are stored with "" in DB so must be removed.
                        #pruningVlan = port[29]

                        switchIntType = vlanSql[4]
                        accessVlan = vlanSql[8]
                        VoiceVlan = vlanSql[9]
                        nativeVlan = vlanSql[10]
                        allowedVlan = vlanSql[11]
                        if allowedVlan:
                            if allowedVlan.find('\"'):
                                allowedVlan = allowedVlan.strip('\"') #Multiple VLAN's are stored with "" in DB so must be removed.
                        pruningVlan = vlanSql[12]


                        #Remove the P & S at the beginning (respectivly)
                        panelID = panelID[1:]
                        #newStackID = newStackID[1:]
                        intStackID = int(panelID) - int(newStackID)
                        intStackID+=1 #Regards of position, it will always be +1 over the difference of the positions
                        intface = str("gi{}/0/{}").format(intStackID,switchInt)
                        intconf.append(str("int {}").format(intface))
                        intconf.append(str(" description {}").format(intDescription))

                        if switchIntType == "Access":
                            intconf.append(str(" switchport mode {}").format(switchIntType))
                            intconf.append(str(" switchport nonegotiate"))
                            intconf.append(str(" storm-control broadcast level 2"))
                            intconf.append(str(" storm-control action shutdown"))
                            intconf.append(str(" spanning-tree portfast"))
                            intconf.append(str(" spanning-tree bpduguard enable"))

                            if accessVlan:
                                #print("Access Vlan!")
                                intconf.append(str(" switchport access vlan {}").format(accessVlan))
                                if VoiceVlan:
                                    #print("Voice Vlan!")
                                    intconf.append(str(" switchport voice vlan {}").format(VoiceVlan))
                                intconf.append(str(" switchport port-security"))
                                intconf.append(str(" switchport port-security maximum 1"))
                                intconf.append(str(" switchport port-security aging time 10"))
                                intconf.append(str(" switchport port-security mac-address sticky"))
                                intconf.append(str(" spanning-tree guard root"))
                                intconf.append(str(" ip arp inspection limit rate 100"))
                                intconf.append(str(" auto qos trust dscp"))
                            else:
                                #May need to add a default if it doesn't have one.
                                #print("No Access VLAN! Setting default.")
                                intconf.append(str(" switchport access vlan {}").format(defaultAccessVLAN))
                                intconf.append(str(" ip arp inspection limit rate 15"))



                        elif switchIntType == "Trunk":
                            intconf.append(str(" no switchport access vlan {}").format(defaultAccessVLAN))
                            intconf.append(str(" switchport mode {}").format(switchIntType))

                            if nativeVlan:
                                intconf.append(str(" switchport trunk native vlan {}").format(nativeVlan))
                            if allowedVlan:
                                intconf.append(str(" switchport trunk allowed vlan {}").format(allowedVlan))
                            if pruningVlan:
                                intconf.append(str(" switchport trunk allowed vlan {}").format(pruningVlan))
                            intconf.append(str(" switchport nonegotiate"))
                            intconf.append(str(" auto qos trust dscp"))

                        elif switchIntType == "L3":
                            intconf.append(str(" no switchport"))
                        else:
                            #print("No mode was set.  Applying the 'default'.")
                            #Need to add some defaults.
                            intconf.append(str("switchport mode access"))
                            intconf.append(str("switchport access vlan {}").format(defaultAccessVLAN))
                        #print(intconf)




                #intconf.append(str(endCfg))
                #intconf.appent(str(configWrite)) #Uncomment to save as part of runtime
                configSend.extend(intconf)

                #console access
                #configSend.append(confgCmd)
                configSend.append(str("logging console"))
                configSend.append(str(" line con 0"))
                configSend.append(str(" logging synchronous"))
                configSend.append(str(" exec-timeout 30 0"))
                configSend.append(str(" stopbits 1"))
                configSend.append(str("line vty 0 4"))
                configSend.append(str(" access-class 22 in"))
                configSend.append(str(" logging synchronous"))
                configSend.append(str(" exec-timeout 30 0"))
                configSend.append(str(" transport preferred ssh"))
                configSend.append(str(" transport input ssh"))
                configSend.append(str(" transport output ssh"))
                configSend.append(str("line vty 5 15"))
                configSend.append(str(" access-class 22 in"))
                configSend.append(str(" logging synchronous"))
                configSend.append(str(" exec-timeout 30 0"))
                configSend.append(str(" transport preferred ssh"))
                configSend.append(str(" transport input ssh"))
                configSend.append(str(" transport output ssh"))
                #configSend.append(str(endCfg))
                #configSend.append(confgCmd)
                configSend.append(str("enable secret 5 $1$MoaU$UHmPxhK9GkitdkNQIW30S/"))
                configSend.append(str("username root privilege 15 secret 5 $1$ADF9$lxyiwxXzuZzxTRzqhvcY11"))
                configSend.append(str("username presidio privilege 15 secret Netech4ever!"))
                configSend.append(str("aaa new-model"))
                configSend.append(str("aaa authentication login default group tacacs+ local-case enable"))
                configSend.append(str("aaa authorization console"))
                configSend.append(str("aaa authorization exec default group tacacs+ local if-authenticated"))
                configSend.append(str("aaa accounting exec default start-stop group tacacs+"))
                configSend.append(str("aaa accounting commands 1 default start-stop group tacacs+"))
                configSend.append(str("aaa accounting commands 15 default start-stop group tacacs+"))
                configSend.append(str("aaa accounting network default start-stop group tacacs+"))
                configSend.append(str("aaa accounting connection default start-stop group tacacs+"))
                configSend.append(str("aaa accounting system default start-stop group tacacs+"))
                configSend.append(str("aaa session-id common"))
                configSend.append(str("aaa authorization commands 1 default group tacacs+ if-authenticated"))
                configSend.append(str("aaa authorization commands 15 default group tacacs+ if-authenticated"))
                configSend.append(str("aaa authentication webauth default group tacacs+ local enable"))
                configSend.append(str(exitCfg))

                #Config Build Complete.  Print to verify
                print("Sending Config: ")
                #pprint(configSend)
                ConfigWrite(closet,hostname,configSend)

        sys.exit()
        #ConfigWrite(hostname,configSend)
    elif runTimeOption == "6":
        #sqlConn.close()
        logFile.close()
        sys.exit()
    else:
        print('Invalid selection.\r\n')

#pprint(interfaceDict)
sqlConn.close()
logFile.close()
sys.exit()
