from libs.GXDLMSReader import GXDLMSReader
from libs.GXSettings import GXSettings

# global COM
# global ADDRESS
# global BAUD

# COM = 3
# ADDRESS = 0
# BAUD = 115200


def connect(com):
    settings = GXSettings()
    settings.getParameters("COM", f'COM{com}', password='1234567898765432', authentication="High", serverAddress=127,
                           logicalAddress=1, clientAddress=48, baudRate=9600)
    reader = GXDLMSReader(settings.client, settings.media, settings.trace, settings.invocationCounter)
    return reader, settings
