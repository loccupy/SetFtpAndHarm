from datetime import datetime, timedelta
import os
import random
import time
import traceback

from gurux_common import ReceiveParameters, GXCommon, TimeoutException
from gurux_common.enums import TraceLevel
from gurux_common.io import Parity, StopBits
from gurux_dlms import GXByteBuffer, GXReplyData, GXDLMSTranslator, GXDLMSException, GXDLMSAccessItem, \
    GXTime, GXDateTime, GXDate
from gurux_dlms.enums import InterfaceType, ObjectType, Authentication, Conformance, DataType, \
    Security, AssociationResult, SourceDiagnostic, AccessServiceCommandType
from gurux_dlms.objects import GXDLMSObject, GXDLMSObjectCollection, GXDLMSData, GXDLMSRegister, \
    GXDLMSDemandRegister, GXDLMSProfileGeneric, GXDLMSExtendedRegister, GXDLMSDisconnectControl, \
    GXDLMSActivityCalendar, GXDLMSDayProfile, GXDLMSWeekProfile, GXDLMSSeasonProfile, GXDLMSDayProfileAction, \
    GXDLMSScriptTable, GXDLMSSpecialDaysTable
from gurux_net import GXNet


class GXDLMSReader(GXDLMSDisconnectControl):
    # pylint: disable=too-many-public-methods, too-many-instance-attributes
    def __init__(self, client, media, trace, invocationCounter):
        super().__init__()
        # pylint: disable=too-many-arguments
        self.replyBuff = bytearray(8 + 1024)
        self.waitTime = 1000
        # self.logFile = open("logFile.txt", "w")
        self.trace = trace
        self.media = media
        self.invocationCounter = invocationCounter
        self.client = client
        self.deviceType = ""
        # if self.trace > TraceLevel.WARNING:
        #     print("Authentication: " + str(self.client.authentication))
        #     print("ClientAddress: " + hex(self.client.clientAddress))
        #     print("ServerAddress: " + hex(self.client.serverAddress))

    def disconnect(self):
        # pylint: disable=broad-except
        if self.media and self.media.isOpen():
            print("DisconnectRequest")
            reply = GXReplyData()
            self.readDLMSPacket(self.client.disconnectRequest(), reply)

    def release(self):
        # pylint: disable=broad-except
        if self.media and self.media.ismedia():
            print("DisconnectRequest")
            reply = GXReplyData()
            try:
                # Release is call only for secured connections.
                # All meters are not supporting Release and it's causing
                # problems.
                if self.client.interfaceType == InterfaceType.WRAPPER or self.client.ciphering.security != Security.NONE:
                    self.readDataBlock(self.client.releaseRequest(), reply)
            except Exception:
                pass
                #  All meters don't support release.

    def close(self):
        # pylint: disable=broad-except
        if self.media and self.media.isOpen():
            # print("DisconnectRequest")
            reply = GXReplyData()
            try:
                # Release is call only for secured connections.
                # All meters are not supporting Release and it's causing
                # problems.
                if self.client.interfaceType == InterfaceType.WRAPPER or self.client.ciphering.security != Security.NONE:
                    self.readDataBlock(self.client.releaseRequest(), reply)
            except Exception:
                pass
                #  All meters don't support release.
            reply.clear()
            self.readDLMSPacket(self.client.disconnectRequest(), reply)
            self.media.close()

    @classmethod
    def now(cls):
        return datetime.now().strftime("%H:%M:%S")

    def writeTrace(self, line, level):
        # print(line)
        # self.logFile.write(line + "\n")
        pass

    def readDLMSPacket(self, data, reply=None):
        if not reply:
            reply = GXReplyData()
        if isinstance(data, bytearray):
            self.readDLMSPacket2(data, reply)
        elif data:
            for it in data:
                reply.clear()
                self.readDLMSPacket2(it, reply)

    def readDLMSPacket2(self, data, reply):
        if not data:
            return
        notify = GXReplyData()
        reply.error = 0
        eop = 0x7E
        # In network connection terminator is not used.
        if self.client.interfaceType == InterfaceType.WRAPPER and isinstance(self.media, GXNet):
            eop = None
        p = ReceiveParameters()
        p.eop = eop
        p.allData = True
        p.waitTime = self.waitTime
        if eop is None:
            p.Count = 8
        else:
            p.Count = 5
        self.media.eop = eop
        rd = GXByteBuffer()
        with self.media.getSynchronous():
            if not reply.isStreaming():
                if self.trace != TraceLevel.OFF:
                    self.writeTrace("TX: " + self.now() + "\t" + GXByteBuffer.hex(data), TraceLevel.VERBOSE)
                self.media.send(data)
            pos = 0
            try:
                while not self.client.getData(rd, reply, notify):
                    if notify.data.size != 0:
                        if not notify.isMoreData():
                            t = GXDLMSTranslator()
                            xml = t.dataToXml(notify.data)
                            print(xml)
                            notify.clear()
                        continue
                    if not p.eop:
                        p.count = self.client.getFrameSize(rd)
                    while not self.media.receive(p):
                        pos += 1
                        if pos == 3:
                            raise TimeoutException("Failed to receive reply from the device in given time.")
                        print("Data send failed.  Try to resend " + str(pos) + "/3")
                        self.media.send(data, None)
                    rd.set(p.reply)
                    p.reply = None
            except Exception as e:
                self.writeTrace("RX: " + self.now() + "\t" + str(rd), TraceLevel.ERROR)
                raise e
            if self.trace != TraceLevel.OFF:
                self.writeTrace("RX: " + self.now() + "\t" + str(rd), TraceLevel.VERBOSE)
            # print("RX:" + str(rd))
            if reply.error != 0:
                # print('reply.error >>>>>>>>>>', reply.error)
                raise GXDLMSException(reply.error)

    def readDataBlock(self, data, reply):
        if data:
            if isinstance(data, (list)):
                for it in data:
                    reply.clear()
                    self.readDataBlock(it, reply)
                return reply.error == 0
            else:
                self.readDLMSPacket(data, reply)
                while reply.isMoreData():
                    if reply.isStreaming():
                        data = None
                    else:
                        data = self.client.receiverReady(reply)
                    self.readDLMSPacket(data, reply)

    def initializeOpticalHead(self):
        if self.client.interfaceType == InterfaceType.HDLC_WITH_MODE_E:
            p = ReceiveParameters()
            p.allData = True
            p.eop = '\n'
            p.waitTime = self.waitTime
            with self.media.getSynchronous():
                data = "/?!\r\n"
                self.writeTrace("TX: " + self.now() + "\t" + data, TraceLevel.VERBOSE)
                self.media.send(data)
                if not self.media.receive(p):
                    raise Exception("Failed to received reply from the media.")

                self.writeTrace("RX: " + self.now() + "\t" + str(p.reply), TraceLevel.VERBOSE)
                # If echo is used.
                if data.encode() == p.reply:
                    p.reply = None
                    if not self.media.receive(p):
                        raise Exception("Failed to received reply from the media.")
                    self.writeTrace("RX: " + self.now() + "\t" + str(p.reply), TraceLevel.VERBOSE)

            if not p.reply or p.reply[0] != ord('/'):
                raise Exception("Invalid responce : " + str(p.reply))
            baudrate = chr(p.reply[4])
            if baudrate == '0':
                bitrate = 300
            elif baudrate == '1':
                bitrate = 600
            elif baudrate == '2':
                bitrate = 1200
            elif baudrate == '3':
                bitrate = 2400
            elif baudrate == '4':
                bitrate = 4800
            elif baudrate == '5':
                bitrate = 9600
            elif baudrate == '6':
                bitrate = 19200
            else:
                raise Exception("Unknown baud rate.")

            print("Bitrate is : " + str(bitrate))
            # Send ACK
            # Send Protocol control character
            controlCharacter = ord('2')
            # "2" HDLC protocol procedure (Mode E)
            # Mode control character
            # "2" //(HDLC protocol procedure) (Binary mode)
            modeControlCharacter = ord('2')
            # Set mode E.
            tmp = bytearray([0x06, controlCharacter, ord(baudrate), modeControlCharacter, 13, 10])
            p.reply = None
            with self.media.getSynchronous():
                self.media.send(tmp)
                # This sleep make sure that all meters can be read.
                time.sleep(1)
                self.writeTrace("TX: " + self.now() + "\t" + GXCommon.toHex(tmp), TraceLevel.VERBOSE)
                p.waitTime = 200
                if self.media.receive(p):
                    self.writeTrace("RX: " + self.now() + "\t" + str(p.reply), TraceLevel.VERBOSE)
                self.media.dataBits = 8
                self.media.parity = Parity.NONE
                self.media.stopBits = StopBits.ONE
                self.media.baudRate = bitrate
                # This sleep make sure that all meters can be read.
                time.sleep(1)

    def updateFrameCounter(self):
        if self.invocationCounter and self.client.ciphering is not None and self.client.ciphering.security != Security.NONE:
            self.initializeOpticalHead()
            self.client.proposedConformance |= Conformance.GENERAL_PROTECTION
            add = self.client.clientAddress
            auth = self.client.authentication
            security = self.client.ciphering.security
            challenge = self.client.ctoSChallenge
            try:
                self.client.clientAddress = 16
                self.client.authentication = Authentication.NONE
                self.client.ciphering.security = Security.NONE
                reply = GXReplyData()
                data = self.client.snrmRequest()
                if data:
                    self.readDLMSPacket(data, reply)
                    self.client.parseUAResponse(reply.data)
                    size = self.client.hdlcSettings.maxInfoTX  # + 40
                    self.replyBuff = bytearray(size)
                reply.clear()
                self.readDataBlock(self.client.aarqRequest(), reply)
                self.client.parseAareResponse(reply.data)
                reply.clear()
                d = GXDLMSData(self.invocationCounter)
                self.read(d, 2)
                self.client.ciphering.invocationCounter = 1 + d.value
                print("Invocation counter: " + str(self.client.ciphering.invocationCounter))
                self.disconnect()
                # except Exception as ex:
            finally:
                self.client.clientAddress = add
                self.client.authentication = auth
                self.client.ciphering.security = security
                self.client.ctoSChallenge = challenge

    def initializeConnection(self):
        # print("ReconnectRequest: " + str(self.client.standard))
        if self.client.ciphering.security != Security.NONE:
            print("Security: " + str(self.client.ciphering.security))
            print("System title: " + GXCommon.toHex(self.client.ciphering.systemTitle))
            print("Authentication key: " + GXCommon.toHex(self.client.ciphering.authenticationKey))
            print("Block cipher key: " + GXCommon.toHex(self.client.ciphering.blockCipherKey))
            if self.client.ciphering.dedicatedKey:
                print("Dedicated key: " + GXCommon.toHex(self.client.ciphering.dedicatedKey))
        self.updateFrameCounter()
        self.initializeOpticalHead()
        reply = GXReplyData()
        data = self.client.snrmRequest()
        if data:
            self.readDLMSPacket(data, reply)
            self.client.parseUAResponse(reply.data)
            size = self.client.hdlcSettings.maxInfoTX  # + 40
            self.replyBuff = bytearray(size)
        reply.clear()
        self.readDataBlock(self.client.aarqRequest(), reply)
        self.client.parseAareResponse(reply.data)
        reply.clear()
        if self.client.authentication > Authentication.LOW:
            try:
                for it in self.client.getApplicationAssociationRequest():
                    self.readDLMSPacket(it, reply)
                self.client.parseApplicationAssociationResponse(reply.data)
                self.setDeviceType()
            except GXDLMSException as ex:
                # Invalid password.
                raise GXDLMSException(AssociationResult.PERMANENT_REJECTED, SourceDiagnostic.AUTHENTICATION_FAILURE)

    def setDeviceType(self):
        model_num = self.read(GXDLMSData("0.0.96.1.9.255"), 2).decode()
        if "3T" in model_num:
            self.deviceType = "TT"
        elif ".3" in model_num:
            self.deviceType = "3PH"
        else:
            self.deviceType = "1PH"

    def read(self, item, attributeIndex):
        data = self.client.read(item, attributeIndex)[0]
        reply = GXReplyData()
        self.readDataBlock(data, reply)
        # Update data type on read.
        if item.getDataType(attributeIndex) == DataType.NONE:
            item.setDataType(attributeIndex, reply.valueType)
        return self.client.updateValue(item, attributeIndex, reply.value)

    def readType(self, item, attributeIndex):
        data = self.client.read(item, attributeIndex)[0]
        reply = GXReplyData()
        self.readDataBlock(data, reply)
        # Update data type on read.
        if item.getDataType(attributeIndex) == DataType.NONE:
            item.setDataType(attributeIndex, reply.valueType)
        self.client.updateValue(item, attributeIndex, reply.value)
        return item.getDataType(attributeIndex)

    def read_week_profile(self, item, attributeIndex):
        data = self.client.read(item, attributeIndex)[0]
        reply = GXReplyData()
        self.readDataBlock(data, reply)
        data = reply.value
        for _ in data:
            _[0] = _[0].decode('utf-8')
            _[1] = _[1:]
            del _[2:]
        return data

    def _season_parser(self, gx_time):
        if len(gx_time) == 24:
            gx_time = gx_time[:-7]

        time_list = list(gx_time)
        time_list[0], time_list[1], time_list[3], time_list[4] = time_list[3], time_list[4], time_list[0], time_list[1]

        if len(time_list) == 17:
            time_list.insert(6, '20')
        elif len(time_list) == 14:
            time_list.insert(5, str(f'/{datetime.datetime.today().year}'))
            # print(time_list)

        return ''.join(time_list)

    def read_season_profile(self, item, attributeIndex):
        data = self.client.read(item, attributeIndex)[0]
        reply = GXReplyData()
        self.readDataBlock(data, reply)
        data = reply.value
        time_ = self.client.updateValue(item, attributeIndex, reply.value)
        time_ = [str(time_[i]).partition(' ') for i in range(len(time_))]
        for i, _ in enumerate(data):
            _[0] = _[0].decode('utf-8')
            _[1] = self._season_parser(time_[i][-1])
            _[2] = _[2].decode('utf-8')
        return data

    def readList(self, list_):
        if list_:
            data = self.client.readList(list_)
            reply = GXReplyData()
            values = list()
            for it in data:
                self.readDataBlock(it, reply)
                if reply.value:
                    values.extend(reply.value)
                reply.clear()
            if len(values) != len(list_):
                raise ValueError("Invalid reply. Read items count do not match.")
            self.client.updateValues(list_, values)
            return values

    def write(self, item, attributeIndex):
        data = self.client.write(item, attributeIndex)
        self.readDLMSPacket(data)

    def write_with_type(self, item, attributeIndex, type):
        data = self.client.write_with_type(item, attributeIndex, type)
        self.readDLMSPacket(data)

    def writeList(self, list_):
        data = self.client.writeList(list_)
        self.readDLMSPacket(data)

    def write_negative(self, item, attributeIndex, offset):
        data = self.client.write(item, attributeIndex, offset)
        self.readDLMSPacket(data)

    def readRowsByEntry(self, pg, index, count):
        data = self.client.readRowsByEntry(pg, index, count)
        reply = GXReplyData()
        self.readDataBlock(data, reply)
        return self.client.updateValue(pg, 2, reply.value)

    def readRowsIndexToIndex(self, pg, from_index, to_index):
        data = self.client.readRowsIndexToIndex(pg, from_index, to_index)
        reply = GXReplyData()
        self.readDataBlock(data, reply)
        return self.client.updateValue(pg, 2, reply.value)

    def readRowsByRange(self, pg, start, end):
        reply = GXReplyData()
        data = self.client.readRowsByRange(pg, start, end)
        self.readDataBlock(data, reply)
        return self.client.updateValue(pg, 2, reply.value)

    # Read values using Access request.
    def readByAccess(self, list_):
        if list_:
            reply = GXReplyData()
            data = self.client.accessRequest(None, list_)
            self.readDataBlock(data, reply)
            self.client.parseAccessResponse(list_, reply.data)

    def readScalerAndUnits(self):
        # pylint: disable=broad-except
        objs = self.client.objects.getObjects(
            [ObjectType.REGISTER, ObjectType.EXTENDED_REGISTER, ObjectType.DEMAND_REGISTER])
        list_ = list()
        if self.client.negotiatedConformance & Conformance.ACCESS != 0:
            for it in objs:
                if isinstance(it, (GXDLMSRegister, GXDLMSExtendedRegister)):
                    list_.append(GXDLMSAccessItem(AccessServiceCommandType.GET, it, 3))
                elif isinstance(it, (GXDLMSDemandRegister)):
                    list_.append(GXDLMSAccessItem(AccessServiceCommandType.GET, it, 4))
            self.readByAccess(list_)
            return
        try:
            if self.client.negotiatedConformance & Conformance.MULTIPLE_REFERENCES != 0:
                for it in objs:
                    if isinstance(it, (GXDLMSRegister, GXDLMSExtendedRegister)):
                        list_.append((it, 3))
                    elif isinstance(it, (GXDLMSDemandRegister,)):
                        list_.append((it, 4))
                self.readList(list_)
        except Exception:
            self.client.negotiatedConformance &= ~Conformance.MULTIPLE_REFERENCES
        if self.client.negotiatedConformance & Conformance.MULTIPLE_REFERENCES == 0:
            for it in objs:
                try:
                    if isinstance(it, (GXDLMSRegister,)):
                        self.read(it, 3)
                    elif isinstance(it, (GXDLMSDemandRegister,)):
                        self.read(it, 4)
                except Exception:
                    pass

    def getProfileGenericColumns(self):
        # pylint: disable=broad-except
        profileGenerics = self.client.objects.getObjects(ObjectType.PROFILE_GENERIC)
        for pg in profileGenerics:
            self.writeTrace("Profile Generic " + str(pg.name) + "Columns:", TraceLevel.INFO)
            try:
                if pg.canRead(3):
                    self.read(pg, 3)
                if self.trace > TraceLevel.WARNING:
                    sb = ""
                    for k, _ in pg.captureObjects:
                        if sb:
                            sb += " | "
                        sb += str(k.name)
                        sb += " "
                        desc = k.description
                        if desc:
                            sb += desc
                    self.writeTrace(sb, TraceLevel.INFO)
            except Exception as ex:
                self.writeTrace("Err! Failed to read columns:" + str(ex), TraceLevel.ERROR)

    def readProfileGenericColumns(self, pg):
        # pylint: disable=broad-except
        cols = []
        try:
            if pg.canRead(3):
                self.read(pg, 3)
                sb = ""
                for k, _ in pg.captureObjects:
                    cols.append(str(k.name))
        except Exception as ex:
            self.writeTrace("Err! Failed to read columns:" + str(ex), TraceLevel.ERROR)
        return cols

    def getReadOut(self):
        # pylint: disable=unidiomatic-typecheck, broad-except
        for it in self.client.objects:
            if type(it) == GXDLMSObject:
                print("Unknown Interface: " + it.objectType.__str__())
                continue
            if isinstance(it, GXDLMSProfileGeneric):
                continue

            self.writeTrace("-------- Reading " + str(it.objectType) + " " + str(it.name) + " " + it.description,
                            TraceLevel.INFO)
            for pos in it.getAttributeIndexToRead(True):
                try:
                    if it.canRead(pos):
                        val = self.read(it, pos)
                        self.showValue(pos, val)
                    else:
                        self.writeTrace("Attribute" + str(pos) + " is not readable.", TraceLevel.INFO)
                except Exception as ex:
                    self.writeTrace("Error! Index: " + str(pos) + " " + str(ex), TraceLevel.ERROR)
                    self.writeTrace(str(ex), TraceLevel.ERROR)
                    if not isinstance(ex, (GXDLMSException, TimeoutException)):
                        traceback.print_exc()

    def showValue(self, pos, val):
        if isinstance(val, (bytes, bytearray)):
            val = GXByteBuffer(val)
        elif isinstance(val, list):
            str_ = ""
            for tmp in val:
                if str_:
                    str_ += ", "
                if isinstance(tmp, bytes):
                    str_ += GXByteBuffer.hex(tmp)
                else:
                    str_ += str(tmp)
            val = str_
        self.writeTrace("Index: " + str(pos) + " Value: " + str(val), TraceLevel.INFO)

    def getProfileGenerics(self):
        # pylint: disable=broad-except,too-many-nested-blocks
        cells = []
        profileGenerics = self.client.objects.getObjects(ObjectType.PROFILE_GENERIC)
        for it in profileGenerics:
            self.writeTrace("-------- Reading " + str(it.objectType) + " " + str(it.name) + " " + it.description,
                            TraceLevel.INFO)
            entriesInUse = self.read(it, 7)
            entries = self.read(it, 8)
            self.writeTrace("Entries: " + str(entriesInUse) + "/" + str(entries), TraceLevel.INFO)
            pg = it
            if entriesInUse == 0 or not pg.captureObjects:
                continue
            try:
                cells = self.readRowsByEntry(pg, 1, 1)
                if self.trace > TraceLevel.WARNING:
                    for rows in cells:
                        for cell in rows:
                            if isinstance(cell, bytearray):
                                self.writeTrace(GXByteBuffer.hex(cell) + " | ", TraceLevel.INFO)
                            else:
                                self.writeTrace(str(cell) + " | ", TraceLevel.INFO)
                        self.writeTrace("", TraceLevel.INFO)
            except Exception as ex:
                self.writeTrace("Error! Failed to read first row: " + str(ex), TraceLevel.ERROR)
                if not isinstance(ex, (GXDLMSException, TimeoutException)):
                    traceback.print_exc()
            try:
                start = datetime.datetime.now()
                end = start
                start = start.replace(hour=0, minute=0, second=0, microsecond=0)
                end = end.replace(minute=0, second=0, microsecond=0)
                cells = self.readRowsByRange(it, start, end)
                for rows in cells:
                    row = ""
                    for cell in rows:
                        if row:
                            row += " | "
                        if isinstance(cell, bytearray):
                            row += GXByteBuffer.hex(cell)
                        else:
                            row += str(cell)
                    self.writeTrace(row, TraceLevel.INFO)
            except Exception as ex:
                self.writeTrace("Error! Failed to read last day: " + str(ex), TraceLevel.ERROR)

    def getAssociationView(self):
        reply = GXReplyData()
        self.readDataBlock(self.client.getObjectsRequest(), reply)
        self.client.parseObjects(reply.data, True, False)
        # Access rights must read differently when short Name referencing is used.
        if not self.client.useLogicalNameReferencing:
            sn = self.client.objects.findBySN(0xFA00)
            if sn and sn.version > 0:
                try:
                    self.read(sn, 3)
                except (GXDLMSException):
                    self.writeTrace("Access rights are not implemented for the meter.", TraceLevel.INFO)

    def readAll(self, outputFile):
        try:
            read = False
            self.initializeConnection()

            if outputFile and os.path.exists(outputFile):
                try:
                    c = GXDLMSObjectCollection.load(outputFile)
                    self.client.objects.extend(c)
                    if self.client.objects:
                        read = True
                except Exception:
                    read = False
            if not read:
                # Вот эта штука собирает коллекцию
                self.getAssociationView()
                self.readScalerAndUnits()
                self.getProfileGenericColumns()
            self.getReadOut()
            self.getProfileGenerics()
            if outputFile:
                self.client.objects.save(outputFile)
        except (KeyboardInterrupt, SystemExit):
            # Don't send anything if user is closing the app.
            self.media = None
            raise
        finally:
            self.close()

    def relay_actions(self, actions):
        reply = GXReplyData()
        dc = GXDLMSDisconnectControl("0.0.96.3.10.255")
        if actions == 0:
            self.readDataBlock(dc.remoteDisconnect(self.client), reply)
        elif actions == 1:
            self.readDataBlock(dc.remoteReconnect(self.client), reply)

    def relay_disconnect(self):
        self.relay_actions(0)

    def relay_reconnect(self):
        self.relay_actions(1)

    # convert date and time accounting difference 2 hours 59 munites 1 second
    def normalize_time(self, write_time):  # преобразует время формата datetime, вычитая 2 часа 59 минут 1 секунду
        write_time = write_time - timedelta(hours=0, minutes=0, seconds=0)
        return write_time

    def check_period_profile(self, pg, capture_period=None):
        self.read(pg, 3)
        if not capture_period:
            capture_period = self.read(pg, 4)
        buffer = self.read(pg, 2)
        if not buffer:
            return 0, 0
        delta = datetime.timedelta(hours=2, minutes=59)
        for _ in buffer:
            _[0] = datetime.datetime.strptime(str(_[0]), '%m/%d/%y %H:%M:%S')
        first_record = buffer[0][0]
        last_record = buffer[-1][0]
        print(first_record)
        print(last_record)
        time_diff = int(((last_record - first_record).total_seconds()) // capture_period) + 1
        return len(buffer), time_diff

    # check billing day and convert to int format for further test
    def check_billing_day(self, day):
        return int(day[:3].replace("/", ""))

    # convert date and time to tuple for further write
    def convert_date_time_to_tuple(self, date_time):
        day = int(date_time[:2])
        month = int(date_time[3:5])
        year = int(date_time[6:10])
        hours = int(date_time[11:13])
        minutes = int(date_time[14:16])
        seconds = int(date_time[17:])
        return year, month, day, hours, minutes, seconds

    # convert time (e.g. tariff interval start) to tuple(hours, min, sec)
    def convert_time_to_tuple(self, time):
        hours = int(time[:2])
        minutes = int(time[3:5])
        seconds = int(time[6:])
        return hours, minutes, seconds

    # convert list(hours, min, sec) to standard time view - HH:MM:SS
    def convert_list_to_time(self, lst):
        wr_time = ''
        if lst[0] < 10:
            wr_time += '0' + str(lst[0]) + ':'
        else:
            wr_time += str(lst[0]) + ':'
        if lst[1] < 10:
            wr_time += '0' + str(lst[1]) + ':'
        else:
            wr_time += str(lst[1]) + ':'
        wr_time += '00'
        return wr_time

    def convert_list_to_datetime(self, lst):
        wr_datetime = ''
        if lst[2] < 10:
            wr_datetime += '0' + str(lst[2]) + '/'
        else:
            wr_datetime += str(lst[2]) + '/'
        if lst[1] < 10:
            wr_datetime += '0' + str(lst[1]) + '/'
        else:
            wr_datetime += str(lst[1]) + '/'
        wr_datetime += str(lst[0])
        wr_datetime += ' 00:00:00'
        return wr_datetime

    # check whether datetime format is correct
    def check_datetime_format(self, date_time):
        status = False
        day = int(date_time[3:5])
        month = int(date_time[:2])
        year = int(date_time[6:8])
        hour = int(date_time[9:11])
        minute = int(date_time[12:14])
        second = int(date_time[15:])
        if len(date_time) == 17 and (0 < day < 32) and (0 < month < 13) and (year < 2030) and (hour < 24) and (
                minute < 60) and (second < 60):
            status = True
        return status


    def add_day_profile(self, calendar, day_count, interval_count, tariff_times=None, selectors=None):
        calendar.dayProfileTablePassive = []
        # An array with timings for all days
        if tariff_times is None:
            tariff_times = ["00:00:00", "01:00:00", "02:10:00", "03:20:00", "04:00:00", "05:35:00", "06:00:00",
                            "07:05:00", "08:11:00", "09:00:00", "10:00:00", "11:00:00", "12:00:00", "13:00:00",
                            "14:10:00", "15:00:00", "16:55:00", "17:00:00", "18:00:00", "19:00:00", "20:00:00",
                            "21:00:00", "22:00:00", "23:00:00"]
        # Tariff selectors
        if selectors is None:
            selectors = [1, 2, 3, 4]
        for day in range(day_count):
            # Cycle for adding the id of the days
            calendar.dayProfileTablePassive.append(GXDLMSDayProfile())
            calendar.dayProfileTablePassive[day].dayId = day + 1
            calendar.dayProfileTablePassive[day].daySchedules = []
            # Cycle for creating a schedule for days
            for time in range(interval_count):
                calendar.dayProfileTablePassive[day].daySchedules.append(GXDLMSDayProfileAction())
                # Adding time to the daySchedule line
                calendar.dayProfileTablePassive[day].daySchedules[time].startTime = GXTime(tariff_times[time],
                                                                                           "%H:%M:%S")
                # Adding script to the daySchedule line
                calendar.dayProfileTablePassive[day].daySchedules[time].scriptLogicalName = "0.0.10.0.100.255"
                # Adding tariff to the daySchedule line
                calendar.dayProfileTablePassive[day].daySchedules[time].scriptSelector = random.choice(selectors)

    def add_day_profile_in_activity_calendar(self, calendar, data):
        calendar.dayProfileTablePassive = []
        for value, elem in enumerate(data):
            day_id = elem[0]
            calendar.dayProfileTablePassive.append(GXDLMSDayProfile())
            calendar.dayProfileTablePassive[value].dayId = day_id
            calendar.dayProfileTablePassive[value].daySchedules = []
            for val, period in enumerate(elem[1]):
                calendar.dayProfileTablePassive[day_id - 1].daySchedules.append(GXDLMSDayProfileAction())
                calendar.dayProfileTablePassive[day_id - 1].daySchedules[val].startTime = \
                    GXTime(period[0], "%H:%M:%S")
                calendar.dayProfileTablePassive[day_id - 1].daySchedules[val].scriptLogicalName = "0.0.10.0.100.255"
                # Adding tariff to the daySchedule line
                calendar.dayProfileTablePassive[day_id - 1].daySchedules[val].scriptSelector = period[1]

        return calendar.dayProfileTablePassive

    def add_special_days_table(self, days):
        # days.entries = list()
        # days.entries.append(1)
        date_ = [2022, 1, 1, 0, 0, 0]
        days.entry.date = GXDateTime(datetime.datetime(date_[0], date_[1], date_[2], date_[3],
                                                       date_[4], date_[5]))
        days.entry.index = 1
        days.entry.dayId = 1
        return days

    def to_ascii(self, name):
        s = ''
        for i in name:
            s += str(hex(ord(i)))[2:]
        return s
    def add_week_profile(self, calendar, week_count, dayIds=None, week_names = None):
        calendar.weekProfileTablePassive = []
        # Create array with days names
        week_days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        # If the names of the weeks are not specified
        if not week_names:
            # Create array with weeks names
            week_names = ['week1', 'Week2', 'week3', 'week4']
        for week in range(week_count):
            # If the weekly rate is not specified
            if not dayIds:
                dayIds = [random.choice(range(1, 5)) for i in range(7)]
            # We writing a new week and give it a name
            calendar.weekProfileTablePassive.append(GXDLMSWeekProfile())
            calendar.weekProfileTablePassive[week].name = self.to_ascii(week_names[week])
            for day in week_days:
                setattr(calendar.weekProfileTablePassive[week], day, dayIds[week_days.index(day)])
    # add new week to week profile

    def add_season_profile(self, calendar, season_count, start_time=None):
        calendar.seasonProfilePassive = []
        # Season names
        season_names = ['season1', 'Season2', '3Season', 'SEASON4']
        if not start_time:
            # Starts time seasons
            start_time = ["01.01.2023 00:00:00", "02.06.2023 00:00:00",
                          "03.09.2023 00:00:00", "04.12.2023 00:00:00"]
        # The cycle of filling the seasons
        for season in range(season_count):
            calendar.seasonProfilePassive.append(GXDLMSSeasonProfile())
            # Season name
            calendar.seasonProfilePassive[season].name = self.to_ascii(season_names[season])
            # Week name in season
            calendar.seasonProfilePassive[season].weekName = calendar.weekProfileTablePassive[season].name
            # Date start time
            calendar.seasonProfilePassive[season].start = GXDateTime(start_time[season], "%d.%m.%Y %H:%M:%S")

    day_id = None
    start_time = None
    script = None
    selector = None

    def _full_time(self, time):
        """ Вспомогательная функция для _read_elem_in_list """
        if len(time) == 1:
            return "0" + time
        else:
            return time

    def _read_elem_in_list(self, data):
        """ Парсит time, script, selector """
        list_ = []
        for elem in data:
            start_time_hour = self._full_time(str(elem[0][0]))
            start_time_minutes = self._full_time(str(elem[0][1]))
            start_time_second = self._full_time(str(elem[0][2]))
            start_time = f"{start_time_hour}:{start_time_minutes}:{start_time_second}"
            script_ = bytes(elem[1])
            script_ = '.'.join([str(el) for el in script_])
            selector_ = elem[2]
            list_.append(start_time)
            list_.append(script_)
            list_.append(selector_)
        return list_

    def _parser_for_day_profile(self, data):
        list_ = []
        """ Если один day id - готово """
        if isinstance(data[0], int):
            day_id = data[0]
            list_.append(day_id)
            data = self._read_elem_in_list(data[1])
            list_.append(data)
            return list_
        else:
            for elem in data:
                data = self._parser_for_day_profile(elem)
                list_.append(data)
            return list_

    def read_activity_calendar(self, item, attributeIndex):
        data = self.client.read(item, attributeIndex)[0]
        reply = GXReplyData()
        self.readDataBlock(data, reply)
        return reply.value

    # -------------------------------------------------- Activity Calendar -------------------------------------------------

    def read_day_profile_active(self):
        ac = GXDLMSActivityCalendar()
        return self._parser_for_day_profile(self.read_activity_calendar(ac, 5))

    def read_day_profile_passive(self):
        ac = GXDLMSActivityCalendar()
        return self._parser_for_day_profile(self.read_activity_calendar(ac, 9))

    # def read_day_profile1(self):
    #     from test_settings import settings
    #     ac = GXDLMSActivityCalendar()
    #     ac.index = 9
    #     return ac.getValue(settings, ac)

    # def write_day_profile(self):
    #     from test_settings import settings
    #     data = GXDLMSClient.createObject(ObjectType.ACTIVITY_CALENDAR)
    #     day_profile = read_day_profile_passive()
    #     data.logicalName = "0.0.13.0.0.255"
    #     #data.dayProfileTablePassive =
    #     ac = GXDLMSActivityCalendar()
    #     ac.index = 9
    #     ac.dayProfileTablePassive = "DayProfileTablePassive"
    #     return ac.getValue(settings=settings, e=ac)

    def activate_passive_calendar(self):
        reply = GXReplyData()
        ac = GXDLMSActivityCalendar()
        self.readDataBlock(ac.activatePassiveCalendar(self.client), reply)

    def script_table(self):
        ac = GXDLMSScriptTable(ln="0.0.10.0.100.255")
        data = ac.getValues()
        return data

    def insert_special_days_table(self, index, date, day_id):
        reply = GXReplyData()
        sdt = GXDLMSSpecialDaysTable()
        sdt.index = index
        sdt.date = GXDate(date)
        sdt.dayId = day_id
        self.readDataBlock(sdt.insert(self.client, sdt), reply)

    def insert_special_days_table_with_type(self, index, date, day_id, type_of_date):
        reply = GXReplyData()
        sdt = GXDLMSSpecialDaysTable()
        sdt.index = index
        sdt.date = GXDate(date)
        sdt.dayId = day_id
        self.readDataBlock(sdt.insert_with_type(self.client, sdt, type_of_date), reply)

    def delete_special_days_table(self, entry):
        reply = GXReplyData()
        sdt = GXDLMSSpecialDaysTable()
        self.readDataBlock(sdt.delete(self.client, entry), reply)

    # ------------------------------------------------- Profile Generic ------------------------------------------------
    def capture_profile(self, obis):
        reply = GXReplyData()
        dc = GXDLMSProfileGeneric(obis)
        self.readDataBlock(dc.capture(self.client), reply)

    def capture_month_profile(self):
        self.capture_profile("1.0.98.1.0.255")

    def capture_day_profile(self):
        self.capture_profile("1.0.98.2.0.255")

    def capture_load_profile_2(self):
        self.capture_profile("1.0.99.2.0.255")

    def capture_load_profile(self):
        self.capture_profile("1.0.99.1.0.255")

    def capture_artur(self):
        self.capture_profile("1.0.99.164.0.255")

    def reset_profile(self, obis):
        reply = GXReplyData()
        dc = GXDLMSProfileGeneric(obis)
        self.readDataBlock(dc.reset(self.client), reply)

    def reset_month_profile(self):
        self.reset_profile("1.0.98.1.0.255")

    def reset_day_profile(self):
        self.reset_profile("1.0.98.2.0.255")

    def reset_load_profile_2(self):
        self.reset_profile("1.0.99.2.0.255")

    def reset_load_profile(self):
        self.reset_profile("1.0.99.1.0.255")

    def read_rows_by_entry(self, pg, index, count):
        return len(self.readRowsByEntry(pg, index, count))

    def read_rows_by_entry_load_profile(self, index, count):
        pg = GXDLMSProfileGeneric("1.0.99.1.0.255")
        self.read(pg, 3)
        return self.read_rows_by_entry(pg, index, count)

    def read_rows_by_entry_load_profile_2(self, index, count):
        pg = GXDLMSProfileGeneric("1.0.99.2.0.255")
        self.read(pg, 3)
        return self.read_rows_by_entry(pg, index, count)

    def read_rows_by_entry_day_profile(self, index, count):
        pg = GXDLMSProfileGeneric("1.0.98.2.0.255")
        self.read(pg, 3)
        return self.read_rows_by_entry(pg, index, count)

    def read_rows_by_entry_month_profile(self, index, count):
        pg = GXDLMSProfileGeneric("1.0.98.1.0.255")
        self.read(pg, 3)
        return self.read_rows_by_entry(pg, index, count)

    def read_rows_by_range(self, pg, start_time, end_time):
        return self.readRowsByRange(pg, start_time, end_time)

    def read_rows_by_range_load_profile(self, start_rime, end_time):
        pg = GXDLMSProfileGeneric("1.0.99.1.0.255")
        self.read(pg, 3)
        return self.read_rows_by_range(pg, start_rime, end_time)

    def read_rows_by_range_load_profile_2(self, start_rime, end_time):
        pg = GXDLMSProfileGeneric("1.0.99.2.0.255")
        self.read(pg, 3)
        return self.read_rows_by_range(pg, start_rime, end_time)

    def read_rows_by_range_day_profile(self, start_rime, end_time):
        pg = GXDLMSProfileGeneric("1.0.98.2.0.255")
        self.read(pg, 3)
        return self.read_rows_by_range(pg, start_rime, end_time)

    def read_rows_by_range_month_profile(self, start_rime, end_time):
        pg = GXDLMSProfileGeneric("1.0.98.1.0.255")
        self.read(pg, 3)
        return self.read_rows_by_range(pg, start_rime, end_time)
