from com.arm.debug.dtsl.configurations import ConfigurationBaseSDF
from com.arm.debug.dtsl.configurations import DTSLv1
from com.arm.debug.dtsl.components import FormatterMode
from com.arm.debug.dtsl.components import AHBAP
from com.arm.debug.dtsl.components import Device
from com.arm.debug.dtsl.components import DeviceInfo
from com.arm.debug.dtsl.configurations.options import IIntegerOption
from com.arm.debug.dtsl.components import DSTREAMTraceCapture
from com.arm.debug.dtsl.components import DSTREAMSTStoredTraceCapture
from com.arm.debug.dtsl.components import DSTREAMPTStoreAndForwardTraceCapture
from com.arm.debug.dtsl.components import DSTREAMPTLiveStoredStreamingTraceCapture
from com.arm.debug.dtsl.components import CSCTI
from com.arm.debug.dtsl.components import ETMv4TraceSource
from com.arm.debug.dtsl.components import V7M_CSTPIU
from com.arm.debug.dtsl.components import V7M_ITMTraceSource
from com.arm.debug.dtsl.configurations import TimestampInfo

coreNames_cortexM7 = ["Cortex-M7"]



class DtslScript(ConfigurationBaseSDF):
    @staticmethod
    def getOptionList():
        return [
            DTSLv1.tabSet("options", "Options", childOptions=
                [DTSLv1.tabPage("trace", "Trace Capture", childOptions=[
                    DTSLv1.integerOption('timestampFrequency', 'Timestamp frequency', defaultValue=25000000, isDynamic=False, description="This value will be used to set the Counter Base Frequency ID Register of the Timestamp generator.\nIt represents the number of ticks per second and is used to translate the timestamp value reported into a number of seconds.\nNote that changing this value may not result in a change in the observed frequency."),
                    DTSLv1.enumOption('traceCapture', 'Trace capture method', defaultValue="none",
                        values = [("none", "None"), DtslScript.getOffChipTraceOption()]),
                ])]
                +[DTSLv1.tabPage("cortexM7", "Cortex-M7", childOptions=[
                    DTSLv1.booleanOption('coreTrace', 'Enable Cortex-M7 core trace', defaultValue=False,
                        childOptions = [
                            DTSLv1.booleanOption('Cortex_M7_0', 'Enable Cortex-M7 trace', defaultValue=True),
                            DTSLv1.booleanOption('timestamp', "Enable ETM Timestamps", description="Controls the output of timestamps into the ETM output streams", defaultValue=True),
                            ETMv4TraceSource.cycleAccurateOption(DtslScript.getSourcesForCoreType("Cortex-M7")),
                        ]
                    ),
                ])]
                +[DTSLv1.tabPage("itm", "ITM", childOptions=[
                    DTSLv1.booleanOption('CSITM', 'Enable CSITM trace', defaultValue=False),
                ])]
            )
        ]
    
    @staticmethod
    def getOffChipTraceOption():
        return ("DSTREAM", "DSTREAM 4GB Trace Buffer",
            DTSLv1.infoElement("dstream", "Off-Chip Trace", "",
                childOptions=[
                    DTSLv1.enumOption('tpiuPortWidth', 'TPIU Port Width', defaultValue="1",
                        values = [("1", "1 bit")], isDynamic=False),
                ]
            )
        )
    
    def __init__(self, root):
        ConfigurationBaseSDF.__init__(self, root)
        
        self.discoverDevices()
    
    # +----------------------------+
    # | Target dependent functions |
    # +----------------------------+
    
    def discoverDevices(self):
        '''Find and create devices'''
        
        # MEMAP devices
        AHBAP(self, self.findDevice("CSMEMAP"), "CSMEMAP")
        
        # Trace start/stop CTIs
        CSCTI(self, self.findDevice("CSCTI"), "CSCTI")
        
        # The ATB stream ID which will be assigned to trace sources.
        streamID = 2
        
        self.cortexM7cores = []
        # Ensure that ETMv4 stream IDs are even
        streamID += (streamID % 2)
        for coreName in (coreNames_cortexM7):
            # Create core
            coreDevice = Device(self, self.findDevice(coreName), coreName)
            deviceInfo = DeviceInfo("core", "Cortex-M7")
            coreDevice.setDeviceInfo(deviceInfo)
            self.cortexM7cores.append(coreDevice)
            self.addDeviceInterface(coreDevice)
            
            # Create CTI (if a CTI exists for this core)
            ctiName = self.getCTINameForCore(coreName)
            if not ctiName is None:
                CSCTI(self, self.findDevice(ctiName), ctiName)
            
            # Create Trace Macrocell (if a macrocell exists for this core - disabled by default - will enable with option)
            tmName = self.getTraceSourceNameForCore(coreName)
            if not tmName == None:
                tm = ETMv4TraceSource(self, self.findDevice(tmName), streamID, tmName)
                streamID += 2
                tm.setEnabled(False)
            
        tpiu = V7M_CSTPIU(self, self.findDevice("CSTPIU"), "CSTPIU", self.getDeviceInterface("CSMEMAP"))
        tpiu.setEnabled(False)
        
        # Assign low stream IDs to ITMs
        itmStreamID = 1
        
        itm = V7M_ITMTraceSource(self, self.findDevice("CSITM"), itmStreamID, "CSITM", self.getDeviceInterfaces().get("Cortex-M7"))
        itm.setPortPrivileges(True, True, True, True)
        itm.setIsSetupByTarget(False)
        itm.setEnabled(False)
        itmStreamID += 1
        
    def createDSTREAMTraceCapture(self, dstreamMode):
        self.DSTREAM = DSTREAMTraceCapture(self, dstreamMode)
        self.addTraceCaptureInterface(self.DSTREAM)
    
    def getDstreamOptionString(self, dstreamMode):
        return "dstream"
    
    def postConnect(self):
        ConfigurationBaseSDF.postConnect(self)
        
        if self.getOptions().getOption("options.trace.timestampFrequency"):
            freq = self.getOptionValue("options.trace.timestampFrequency")
            # Update the value so the trace decoder can access it
            tsInfo = TimestampInfo(freq)
            self.setTimestampInfo(tsInfo)
        
    
    # +--------------------------------+
    # | Callback functions for options |
    # +--------------------------------+
    
    def optionValuesChanged(self):
        '''Callback to update the configuration state after options are changed'''
        if not self.isConnected():
            self.setInitialOptions()
        
        self.updateDynamicOptions()
        
    def setInitialOptions(self):
        '''Set the initial options'''
        
        coreTraceEnabled = self.getOptionValue("options.cortexM7.coreTrace")
        for core in range(len(coreNames_cortexM7)):
            tmName = self.getTraceSourceNameForCore(coreNames_cortexM7[core])
            if tmName:
                coreTM = self.getDeviceInterface(tmName)
                thisCoreTraceEnabled = self.getOptionValue("options.cortexM7.coreTrace.Cortex_M7_%d" % core)
                enableSource = coreTraceEnabled and thisCoreTraceEnabled
                self.setTraceSourceEnabled(tmName, enableSource)
                coreTM.setTimestampingEnabled(self.getOptionValue("options.cortexM7.coreTrace.timestamp"))
        
        itmEnabled = self.getOptionValue("options.itm.CSITM")
        self.setTraceSourceEnabled("CSITM", itmEnabled)
        
        traceMode = self.getOptionValue("options.trace.traceCapture")
        if traceMode != "none":
            # DSTREAM
            if traceMode in ["DSTREAM", "DSTREAM_PT_Store_and_Forward", "DSTREAM_PT_StreamingTrace"]:
                self.createDSTREAMTraceCapture(traceMode)
                if self.getOptions().getOption("options.trace.traceCapture." + self.getDstreamOptionString(traceMode) + ".tpiuPortWidth"):
                    self.setPortWidth(int(self.getOptionValue("options.trace.traceCapture." + self.getDstreamOptionString(traceMode) + ".tpiuPortWidth")))
                
                if self.getOptions().getOption("options.trace.traceCapture." + self.getDstreamOptionString(traceMode) + ".traceBufferSize"):
                    self.setTraceBufferSize(self.getOptionValue("options.trace.traceCapture." + self.getDstreamOptionString(traceMode) + ".traceBufferSize"))
                
            self.enableTraceCapture(traceMode)
            self.configureTraceCapture(traceMode)
            
    def updateDynamicOptions(self):
        '''Update the dynamic options'''
        
    @staticmethod
    def getSourcesForCoreType(coreType):
        '''Get the Trace Sources for a given coreType
           Use parameter-binding to ensure that the correct Sources
           are returned for the core type passed only'''
        def getSources(self):
            return self.getTraceSourcesForCoreType(coreType)
        return getSources
    
class DtslScript_DSTREAM_ST(DtslScript):
    @staticmethod
    def getOptionList():
        return [
            DTSLv1.tabSet("options", "Options", childOptions=
                [DTSLv1.tabPage("trace", "Trace Capture", childOptions=[
                    DTSLv1.integerOption('timestampFrequency', 'Timestamp frequency', defaultValue=25000000, isDynamic=False, description="This value will be used to set the Counter Base Frequency ID Register of the Timestamp generator.\nIt represents the number of ticks per second and is used to translate the timestamp value reported into a number of seconds.\nNote that changing this value may not result in a change in the observed frequency."),
                    DTSLv1.enumOption('traceCapture', 'Trace capture method', defaultValue="none",
                        values = [("none", "None"), DtslScript_DSTREAM_ST.getOffChipTraceOption()]),
                ])]
                +[DTSLv1.tabPage("cortexM7", "Cortex-M7", childOptions=[
                    DTSLv1.booleanOption('coreTrace', 'Enable Cortex-M7 core trace', defaultValue=False,
                        childOptions = [
                            DTSLv1.booleanOption('Cortex_M7_0', 'Enable Cortex-M7 trace', defaultValue=True),
                            DTSLv1.booleanOption('timestamp', "Enable ETM Timestamps", description="Controls the output of timestamps into the ETM output streams", defaultValue=True),
                            ETMv4TraceSource.cycleAccurateOption(DtslScript.getSourcesForCoreType("Cortex-M7")),
                        ]
                    ),
                ])]
                +[DTSLv1.tabPage("itm", "ITM", childOptions=[
                    DTSLv1.booleanOption('CSITM', 'Enable CSITM trace', defaultValue=False),
                ])]
            )
        ]
    
    @staticmethod
    def getOffChipTraceOption():
        return ("DSTREAM", "DSTREAM-ST Streaming Trace",
            DTSLv1.infoElement("dstream", "Off-Chip Trace", "",
                childOptions=[
                    DTSLv1.enumOption('tpiuPortWidth', 'TPIU Port Width', defaultValue="1",
                        values = [("1", "1 bit")], isDynamic=False),
                    DTSLv1.enumOption('traceBufferSize', 'Host Trace Buffer Size', defaultValue="4GB",
                        values = [("64MB", "64MB"), ("128MB", "128MB"), ("256MB", "256MB"), ("512MB", "512MB"), ("1GB", "1GB"), ("2GB", "2GB"), ("4GB", "4GB"), ("8GB", "8GB"), ("16GB", "16GB"), ("32GB", "32GB"), ("64GB", "64GB"), ("128GB", "128GB")], isDynamic=False)
                ]
            )
        )
    
    def createDSTREAMTraceCapture(self, dstreamMode):
        self.DSTREAM = DSTREAMSTStoredTraceCapture(self, dstreamMode)
        self.addTraceCaptureInterface(self.DSTREAM)
        self.addStreamTraceCaptureInterface(self.DSTREAM)
    

class DtslScript_DSTREAM_PT(DtslScript):
    @staticmethod
    def getOptionList():
        return [
            DTSLv1.tabSet("options", "Options", childOptions=
                [DTSLv1.tabPage("trace", "Trace Capture", childOptions=[
                    DTSLv1.integerOption('timestampFrequency', 'Timestamp frequency', defaultValue=25000000, isDynamic=False, description="This value will be used to set the Counter Base Frequency ID Register of the Timestamp generator.\nIt represents the number of ticks per second and is used to translate the timestamp value reported into a number of seconds.\nNote that changing this value may not result in a change in the observed frequency."),
                    DTSLv1.enumOption('traceCapture', 'Trace capture method', defaultValue="none",
                        values = [("none", "None"), DtslScript_DSTREAM_PT.getStoreAndForwardOptions(), DtslScript_DSTREAM_PT.getStreamingTraceOptions()]),
                ])]
                +[DTSLv1.tabPage("cortexM7", "Cortex-M7", childOptions=[
                    DTSLv1.booleanOption('coreTrace', 'Enable Cortex-M7 core trace', defaultValue=False,
                        childOptions = [
                            DTSLv1.booleanOption('Cortex_M7_0', 'Enable Cortex-M7 trace', defaultValue=True),
                            DTSLv1.booleanOption('timestamp', "Enable ETM Timestamps", description="Controls the output of timestamps into the ETM output streams", defaultValue=True),
                            ETMv4TraceSource.cycleAccurateOption(DtslScript.getSourcesForCoreType("Cortex-M7")),
                        ]
                    ),
                ])]
                +[DTSLv1.tabPage("itm", "ITM", childOptions=[
                    DTSLv1.booleanOption('CSITM', 'Enable CSITM trace', defaultValue=False),
                ])]
            )
        ]
    
    @staticmethod
    def getStoreAndForwardOptions():
        return ("DSTREAM_PT_Store_and_Forward", "DSTREAM-PT 8GB Trace Buffer",
            DTSLv1.infoElement("dpt_storeandforward", "Off-Chip Trace", "",
                childOptions=[
                    DTSLv1.enumOption('tpiuPortWidth', 'TPIU Port Width', defaultValue="1",
                        values = [("1", "1 bit")], isDynamic=False),
                ]
            )
        )
    
    @staticmethod
    def getStreamingTraceOptions():
        return ("DSTREAM_PT_StreamingTrace", "DSTREAM-PT Streaming Trace",
            DTSLv1.infoElement("dpt_streamingtrace", "Off-Chip Trace", "",
                childOptions=[
                    DTSLv1.enumOption('tpiuPortWidth', 'TPIU Port Width', defaultValue="1",
                        values = [("1", "1 bit")], isDynamic=False),
                    DTSLv1.enumOption('traceBufferSize', 'Host Trace Buffer Size', defaultValue="4GB",
                        values = [("64MB", "64MB"), ("128MB", "128MB"), ("256MB", "256MB"), ("512MB", "512MB"), ("1GB", "1GB"), ("2GB", "2GB"), ("4GB", "4GB"), ("8GB", "8GB"), ("16GB", "16GB"), ("32GB", "32GB"), ("64GB", "64GB"), ("128GB", "128GB")], isDynamic=False)
                ]
            )
        )
    
    def createDSTREAMTraceCapture(self, dstreamMode):
        if dstreamMode == "DSTREAM_PT_Store_and_Forward":
            self.DSTREAM = DSTREAMPTStoreAndForwardTraceCapture(self, "DSTREAM_PT_Store_and_Forward")
        elif dstreamMode == "DSTREAM_PT_StreamingTrace":
            self.DSTREAM = DSTREAMPTLiveStoredStreamingTraceCapture(self, "DSTREAM_PT_StreamingTrace")
        self.addTraceCaptureInterface(self.DSTREAM)
        self.addStreamTraceCaptureInterface(self.DSTREAM)
    
    def getDstreamOptionString(self, dstreamMode):
        if dstreamMode == "DSTREAM_PT_Store_and_Forward":
            return "dpt_storeandforward"
        if dstreamMode == "DSTREAM_PT_StreamingTrace":
            return "dpt_streamingtrace"
    

class DtslScript_DebugAndOnChipTrace(DtslScript):
    @staticmethod
    def getOptionList():
        return [
        ]
    def setInitialOptions(self):
        '''Set the initial options'''
    

