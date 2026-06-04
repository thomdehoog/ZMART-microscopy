# ====================================================================================
# company: (c) Leica Microsystems CMS GmbH, Mannheim
# created: 8/19/2025 9:06:46 PM
# version: of PYLICamApiConnector.dll = 1.0.108.0
# ====================================================================================

# Import the common runtime language library
import os
import clr
import System
# Import the class String library from the system namespace
from System import String
# Import all classes from the sub namespace System.Collections
from System.Collections import *

# Calculate the absolute path starting from the current script location
base_path = os.path.abspath(os.path.dirname(__file__))

dll_path1 = os.path.join(base_path, 'PYLICamApiConnector.dll')
dll_path2 = os.path.join(base_path, 'LMS.CAM.CORE.dll')
dll_path3 = os.path.join(base_path, 'LMS.CAM.SHARED.OBJECTS.dll')
dll_path4 = os.path.join(base_path, 'Newtonsoft.Json.dll')

dll_ref1 = System.Reflection.Assembly.LoadFile(dll_path1)
dll_ref2 = System.Reflection.Assembly.LoadFile(dll_path2)
dll_ref3 = System.Reflection.Assembly.LoadFile(dll_path3)
dll_ref4 = System.Reflection.Assembly.LoadFile(dll_path4)

# Import static classes and initialize it
# ====================================================================================
LasxApiClientPyModelClassType = dll_ref1.GetType('PYLICamApiConnector.LasxApiClientPyModel')
LasxApiClientPyModel = System.Activator.CreateInstance(LasxApiClientPyModelClassType)

# ====================================================================================

__version__ = '1.0.108.0'
__created__ = '19.08.2025'


# Content Of Class LasxApiClientPyModel
# ====================================================================================
def lasxapiclient_connect(nameOfLasxApiClient: str):
    """category:    PythonConnector
       description: Connect to the LasXApi server synchronously.
       Parameter 1: Name of this LasXApi client.
    """
    LasxApiClientPyModel.Connect(nameOfLasxApiClient)


def lasxapiclient_release(waitbeforeReleaseInMilliSeconds: int):
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.Release(waitbeforeReleaseInMilliSeconds)


def lasxapiclient_get_PyApiClient():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiClient()


def lasxapiclient_set_PyApiClient():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiClient()


def lasxapiclient_get_PyApiSkipAdvanced():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiSkipAdvanced()


def lasxapiclient_set_PyApiSkipAdvanced():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiSkipAdvanced()


def lasxapiclient_get_PyApiSkipWaiting():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiSkipWaiting()


def lasxapiclient_set_PyApiSkipWaiting():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiSkipWaiting()


def lasxapiclient_get_PyApiLoopSettings():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiLoopSettings()


def lasxapiclient_set_PyApiLoopSettings():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiLoopSettings()


def lasxapiclient_get_PyApiPumpSettings():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiPumpSettings()


def lasxapiclient_set_PyApiPumpSettings():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiPumpSettings()


def lasxapiclient_get_PyApiDriftSettings():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiDriftSettings()


def lasxapiclient_set_PyApiDriftSettings():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiDriftSettings()


def lasxapiclient_get_PyApiAssignJob():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiAssignJob()


def lasxapiclient_set_PyApiAssignJob():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiAssignJob()


def lasxapiclient_get_PyApiMessageChat():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiMessageChat()


def lasxapiclient_set_PyApiMessageChat():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiMessageChat()


def lasxapiclient_get_PyApiCommandEcho():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiCommandEcho()


def lasxapiclient_set_PyApiCommandEcho():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiCommandEcho()


def lasxapiclient_get_PyApiCommand():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiCommand()


def lasxapiclient_set_PyApiCommand():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiCommand()


def lasxapiclient_get_PyApiImagePathItem():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiImagePathItem()


def lasxapiclient_set_PyApiImagePathItem():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiImagePathItem()


def lasxapiclient_get_PyApiRareEventItem():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiRareEventItem()


def lasxapiclient_set_PyApiRareEventItem():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiRareEventItem()


def lasxapiclient_get_PyApiStartCamScan():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiStartCamScan()


def lasxapiclient_set_PyApiStartCamScan():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiStartCamScan()


def lasxapiclient_get_PyApiPing():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiPing()


def lasxapiclient_set_PyApiPing():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiPing()


def lasxapiclient_get_PyApiExperimentInformation():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiExperimentInformation()


def lasxapiclient_set_PyApiExperimentInformation():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiExperimentInformation()


def lasxapiclient_get_PyApiErrorInformation():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiErrorInformation()


def lasxapiclient_set_PyApiErrorInformation():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiErrorInformation()


def lasxapiclient_get_PyApiGetJobsInformation():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiGetJobsInformation()


def lasxapiclient_set_PyApiGetJobsInformation():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiGetJobsInformation()


def lasxapiclient_get_PyApiGetConfocalHardwareInfo():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiGetConfocalHardwareInfo()


def lasxapiclient_set_PyApiGetConfocalHardwareInfo():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiGetConfocalHardwareInfo()


def lasxapiclient_get_PyApiGetJobSettingsByName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiGetJobSettingsByName()


def lasxapiclient_set_PyApiGetJobSettingsByName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiGetJobSettingsByName()


def lasxapiclient_get_PyApiGetStatusStedBeamAlignment():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiGetStatusStedBeamAlignment()


def lasxapiclient_set_PyApiGetStatusStedBeamAlignment():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiGetStatusStedBeamAlignment()


def lasxapiclient_get_PyApiStatus():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiStatus()


def lasxapiclient_set_PyApiStatus():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiStatus()


def lasxapiclient_get_PyApiStatusScan():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiStatusScan()


def lasxapiclient_set_PyApiStatusScan():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiStatusScan()


def lasxapiclient_get_PyApiMoveHardwareXY():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiMoveHardwareXY()


def lasxapiclient_set_PyApiMoveHardwareXY():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiMoveHardwareXY()


def lasxapiclient_get_PyApiGetXY():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiGetXY()


def lasxapiclient_set_PyApiGetXY():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiGetXY()


def lasxapiclient_get_PyApiMoveZByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiMoveZByJobName()


def lasxapiclient_set_PyApiMoveZByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiMoveZByJobName()


def lasxapiclient_get_PyApiSelectJobByName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiSelectJobByName()


def lasxapiclient_set_PyApiSelectJobByName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiSelectJobByName()


def lasxapiclient_get_PyApiSetApiInterfaceToUse():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiSetApiInterfaceToUse()


def lasxapiclient_set_PyApiSetApiInterfaceToUse():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiSetApiInterfaceToUse()


def lasxapiclient_get_PyApiStatusProgress():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiStatusProgress()


def lasxapiclient_set_PyApiStatusProgress():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiStatusProgress()


def lasxapiclient_get_PyApiDeleteRareEventList():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiDeleteRareEventList()


def lasxapiclient_set_PyApiDeleteRareEventList():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiDeleteRareEventList()


def lasxapiclient_get_PyApiLoadExperiment():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiLoadExperiment()


def lasxapiclient_set_PyApiLoadExperiment():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiLoadExperiment()


def lasxapiclient_get_PyApiSaveExperiment():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiSaveExperiment()


def lasxapiclient_set_PyApiSaveExperiment():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiSaveExperiment()


def lasxapiclient_get_PyApiStartAFScan():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiStartAFScan()


def lasxapiclient_set_PyApiStartAFScan():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiStartAFScan()


def lasxapiclient_get_PyApiStartScan():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiStartScan()


def lasxapiclient_set_PyApiStartScan():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiStartScan()


def lasxapiclient_get_PyApiAcquireJob():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiAcquireJob()


def lasxapiclient_set_PyApiAcquireJob():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiAcquireJob()


def lasxapiclient_get_PyApiStopCamScan():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiStopCamScan()


def lasxapiclient_set_PyApiStopCamScan():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiStopCamScan()


def lasxapiclient_get_PyApiStopScan():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiStopScan()


def lasxapiclient_set_PyApiStopScan():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiStopScan()


def lasxapiclient_get_PyApiSetZoomByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiSetZoomByJobName()


def lasxapiclient_set_PyApiSetZoomByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiSetZoomByJobName()


def lasxapiclient_get_PyApiSetScanModeByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiSetScanModeByJobName()


def lasxapiclient_set_PyApiSetScanModeByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiSetScanModeByJobName()


def lasxapiclient_get_PyApiSetObjectiveSlotByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiSetObjectiveSlotByJobName()


def lasxapiclient_set_PyApiSetObjectiveSlotByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiSetObjectiveSlotByJobName()


def lasxapiclient_get_PyApiSetImageSizeByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiSetImageSizeByJobName()


def lasxapiclient_set_PyApiSetImageSizeByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiSetImageSizeByJobName()


def lasxapiclient_get_PyApiSetLaserIntensityByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiSetLaserIntensityByJobName()


def lasxapiclient_set_PyApiSetLaserIntensityByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiSetLaserIntensityByJobName()


def lasxapiclient_get_PyApiAddOrRemoveLaserLineByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiAddOrRemoveLaserLineByJobName()


def lasxapiclient_set_PyApiAddOrRemoveLaserLineByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiAddOrRemoveLaserLineByJobName()


def lasxapiclient_get_PyApiSetDetectorGainByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiSetDetectorGainByJobName()


def lasxapiclient_set_PyApiSetDetectorGainByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiSetDetectorGainByJobName()


def lasxapiclient_get_PyApiSetDetectorActiveByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiSetDetectorActiveByJobName()


def lasxapiclient_set_PyApiSetDetectorActiveByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiSetDetectorActiveByJobName()


def lasxapiclient_get_PyApiSetLaserShutterByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiSetLaserShutterByJobName()


def lasxapiclient_set_PyApiSetLaserShutterByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiSetLaserShutterByJobName()


def lasxapiclient_get_PyApiSetTimeDefinitionByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiSetTimeDefinitionByJobName()


def lasxapiclient_set_PyApiSetTimeDefinitionByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiSetTimeDefinitionByJobName()


def lasxapiclient_get_PyApiSaveCurrentSelectedImage():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiSaveCurrentSelectedImage()


def lasxapiclient_set_PyApiSaveCurrentSelectedImage():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiSaveCurrentSelectedImage()


def lasxapiclient_get_PyApiSetLineAverageByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiSetLineAverageByJobName()


def lasxapiclient_set_PyApiSetLineAverageByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiSetLineAverageByJobName()


def lasxapiclient_get_PyApiSetFrameAverageByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiSetFrameAverageByJobName()


def lasxapiclient_set_PyApiSetFrameAverageByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiSetFrameAverageByJobName()


def lasxapiclient_get_PyApiSetLineAccumulationByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiSetLineAccumulationByJobName()


def lasxapiclient_set_PyApiSetLineAccumulationByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiSetLineAccumulationByJobName()


def lasxapiclient_get_PyApiSetFrameAccumulationByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiSetFrameAccumulationByJobName()


def lasxapiclient_set_PyApiSetFrameAccumulationByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiSetFrameAccumulationByJobName()


def lasxapiclient_get_PyApiSetSequentialModeByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiSetSequentialModeByJobName()


def lasxapiclient_set_PyApiSetSequentialModeByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiSetSequentialModeByJobName()


def lasxapiclient_get_PyApiSetScanSpeedByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiSetScanSpeedByJobName()


def lasxapiclient_set_PyApiSetScanSpeedByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiSetScanSpeedByJobName()


def lasxapiclient_get_PyApiSetScannerToResonantByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiSetScannerToResonantByJobName()


def lasxapiclient_set_PyApiSetScannerToResonantByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiSetScannerToResonantByJobName()


def lasxapiclient_get_PyApiSetZStackDefinitionByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiSetZStackDefinitionByJobName()


def lasxapiclient_set_PyApiSetZStackDefinitionByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiSetZStackDefinitionByJobName()


def lasxapiclient_get_PyApiSetZStackSizeByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiSetZStackSizeByJobName()


def lasxapiclient_set_PyApiSetZStackSizeByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiSetZStackSizeByJobName()


def lasxapiclient_get_PyApiCommandSetZStackStepSizeByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiCommandSetZStackStepSizeByJobName()


def lasxapiclient_set_PyApiCommandSetZStackStepSizeByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiCommandSetZStackStepSizeByJobName()


def lasxapiclient_get_PyApiSetPinholeAUByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiSetPinholeAUByJobName()


def lasxapiclient_set_PyApiSetPinholeAUByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiSetPinholeAUByJobName()


def lasxapiclient_get_PyApiSetScanFieldRotationByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiSetScanFieldRotationByJobName()


def lasxapiclient_set_PyApiSetScanFieldRotationByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiSetScanFieldRotationByJobName()


def lasxapiclient_get_PyApiSetFilterWheelSlotByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiSetFilterWheelSlotByJobName()


def lasxapiclient_set_PyApiSetFilterWheelSlotByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiSetFilterWheelSlotByJobName()


def lasxapiclient_get_PyApiSetFilterWheelSpectrumPositionByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiSetFilterWheelSpectrumPositionByJobName()


def lasxapiclient_set_PyApiSetFilterWheelSpectrumPositionByJobName():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiSetFilterWheelSpectrumPositionByJobName()


def lasxapiclient_get_PyApiAcquireSingleImage():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_PyApiAcquireSingleImage()


def lasxapiclient_set_PyApiAcquireSingleImage():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_PyApiAcquireSingleImage()


def lasxapiclient_get_TestTimer():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    return LasxApiClientPyModel.get_TestTimer()


def lasxapiclient_set_TestTimer():
    """category:    PythonConnector
       description: Release the LasXApi server connection
       Parameter 1: A delay in milli seconds before the client will released
    """
    LasxApiClientPyModel.set_TestTimer()


def lasxapiclient_connectAsync(nameOfLasxApiClient: str):
    """category:    PythonConnector
       description: Connect to the LasXApi Server asynchronously.
       Parameter 1: Name of this LasXApi client.
    """
    LasxApiClientPyModel.ConnectAsync(nameOfLasxApiClient)
