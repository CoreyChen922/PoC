# EMACS settings: -*-	tab-width: 2; indent-tabs-mode: t; python-indent-offset: 2 -*-
# vim: tabstop=2:shiftwidth=2:noexpandtab
# kate: tab-width 2; replace-tabs off; indent-width 2;
# 
# ==============================================================================
# Authors:					Patrick Lehmann
# 
# Python Class:			This XSTCompiler compiles VHDL source files to netlists
# 
# Description:
# ------------------------------------
#		TODO:
#		- 
#		- 
#
# License:
# ==============================================================================
# Copyright 2007-2016 Technische Universitaet Dresden - Germany
#											Chair for VLSI-Design, Diagnostics and Architecture
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#		http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
#
# entry point
from PoC.Entity import WildCard

if __name__ != "__main__":
	# place library initialization code here
	pass
else:
	from lib.Functions import Exit
	Exit.printThisIsNoExecutableFile("The PoC-Library - Python Module Compiler.XSTCompiler")


# load dependencies
import re											# used for output filtering

from lib.Functions						import Init
from Base.Exceptions					import NotConfiguredException, PlatformNotSupportedException
from Base.Project							import ToolChain, Tool
from Base.Compiler						import Compiler as BaseCompiler, CompilerException
from ToolChains.Xilinx.Xilinx	import XilinxProjectExportMixIn
from ToolChains.Xilinx.ISE		import ISE


class Compiler(BaseCompiler, XilinxProjectExportMixIn):
	_TOOL_CHAIN =	ToolChain.Xilinx_ISE
	_TOOL =				Tool.Xilinx_XST

	def __init__(self, host, showLogs, showReport):
		super(self.__class__, self).__init__(host, showLogs, showReport)
		XilinxProjectExportMixIn.__init__(self)

		self._device =				None
		self._tempPath =			None
		self._outputPath =		None
		self._ise =						None
		
	def PrepareCompiler(self, binaryPath, version):
		# create the GHDL executable factory
		self._LogVerbose("Preparing Xilinx Synthesis Tool (XST).")
		self._ise =		ISE(self.Host.Platform, binaryPath, version, logger=self.Logger)

	def RunAll(self, fqnList, *args, **kwargs):
		for fqn in fqnList:
			entity = fqn.Entity
			if (isinstance(entity, WildCard)):
				for testbench in entity.GetXSTNetlist():
					try:
						self.Run(testbench, *args, **kwargs)
					except CompilerException:
						pass
			else:
				testbench = entity.XSTNetlist
				try:
					self.Run(testbench, *args, **kwargs)
				except CompilerException:
					pass

	def Run(self, netlist, board, **_):
		self._LogQuiet("IP core: {YELLOW}{0!s}{RESET}".format(netlist.Parent, **Init.Foreground))
		
		self._device =				board.Device
		
		# setup all needed paths to execute xst
		self._PrepareCompilerEnvironment(board.Device)
		self._WriteSpecialSectionIntoConfig(board.Device)

		self._CreatePoCProject(netlist, board)
		self._AddFileListFile(netlist.FilesFile)
		if (netlist.RulesFile is not None):
			self._AddRulesFiles(netlist.RulesFile)

		netlist.XstFile = self._tempPath / (netlist.ModuleName + ".xst")
		netlist.PrjFile = self._tempPath / (netlist.ModuleName + ".prj")

		self._WriteXilinxProjectFile(netlist.PrjFile, "XST")
		self._WriteXstOptionsFile(netlist, board.Device)

		self._LogNormal("Executing pre-processing tasks...")
		self._RunPreCopy(netlist)
		self._RunPreReplace(netlist)

		self._LogNormal("Running Xilinx Synthesis Tool...")
		self._RunCompile(netlist)

		self._LogNormal("Executing post-processing tasks...")
		self._RunPostCopy(netlist)
		self._RunPostReplace(netlist)
		
	def _PrepareCompilerEnvironment(self, device):
		self._LogNormal("preparing synthesis environment...")
		self._tempPath =		self.Host.Directories["XSTTemp"]
		self._outputPath =	self.Host.Directories["PoCNetList"] / str(device)
		super()._PrepareCompilerEnvironment()

	def _WriteSpecialSectionIntoConfig(self, device):
		# add the key Device to section SPECIAL at runtime to change interpolation results
		self.Host.PoCConfig['SPECIAL'] = {}
		self.Host.PoCConfig['SPECIAL']['Device'] =				device.FullName
		self.Host.PoCConfig['SPECIAL']['DeviceSeries'] =	device.Series
		self.Host.PoCConfig['SPECIAL']['OutputDir']	=			self._tempPath.as_posix()

	def _RunCompile(self, netlist):
		reportFilePath = self._tempPath / (netlist.ModuleName + ".log")

		xst = self._ise.GetXst()
		xst.Parameters[xst.SwitchIntStyle] =		"xflow"
		xst.Parameters[xst.SwitchXstFile] =			netlist.ModuleName + ".xst"
		xst.Parameters[xst.SwitchReportFile] =	str(reportFilePath)
		xst.Compile()

	def _WriteXstOptionsFile(self, netlist, device):
		self._LogVerbose("Generating XST options file.")

		# read XST options file template
		self._LogDebug("Reading Xilinx Compiler Tool option file from '{0!s}'".format(netlist.XstTemplateFile))
		if (not netlist.XstTemplateFile.exists()):		raise CompilerException("XST template files '{0!s}' not found.".format(netlist.XstTemplateFile)) from FileNotFoundError(str(netlist.XstTemplateFile))

		with netlist.XstTemplateFile.open('r') as fileHandle:
			xstFileContent = fileHandle.read()

		xstTemplateDictionary = {
			'prjFile':                                                            str(netlist.PrjFile),
			'UseNewParser': self.Host.PoCConfig[netlist.ConfigSectionName]                  ['XSTOption.UseNewParser'],
			'InputFormat': self.Host.PoCConfig[netlist.ConfigSectionName]                   ['XSTOption.InputFormat'],
			'OutputFormat': self.Host.PoCConfig[netlist.ConfigSectionName]                  ['XSTOption.OutputFormat'],
			'OutputName':                                                         netlist.ModuleName,
			'Part':                                                               str(device),
			'TopModuleName':                                                      netlist.ModuleName,
			'OptimizationMode': self.Host.PoCConfig[netlist.ConfigSectionName]              ['XSTOption.OptimizationMode'],
			'OptimizationLevel': self.Host.PoCConfig[netlist.ConfigSectionName]             ['XSTOption.OptimizationLevel'],
			'PowerReduction': self.Host.PoCConfig[netlist.ConfigSectionName]                ['XSTOption.PowerReduction'],
			'IgnoreSynthesisConstraintsFile': self.Host.PoCConfig[netlist.ConfigSectionName]['XSTOption.IgnoreSynthesisConstraintsFile'],
			'SynthesisConstraintsFile':                                           str(netlist.XcfFile),
			'KeepHierarchy': self.Host.PoCConfig[netlist.ConfigSectionName]                 ['XSTOption.KeepHierarchy'],
			'NetListHierarchy': self.Host.PoCConfig[netlist.ConfigSectionName]              ['XSTOption.NetListHierarchy'],
			'GenerateRTLView': self.Host.PoCConfig[netlist.ConfigSectionName]               ['XSTOption.GenerateRTLView'],
			'GlobalOptimization': self.Host.PoCConfig[netlist.ConfigSectionName]            ['XSTOption.Globaloptimization'],
			'ReadCores': self.Host.PoCConfig[netlist.ConfigSectionName]                     ['XSTOption.ReadCores'],
			'SearchDirectories':                                                  '"{0!s}"'.format(self._outputPath),
			'WriteTimingConstraints': self.Host.PoCConfig[netlist.ConfigSectionName]        ['XSTOption.WriteTimingConstraints'],
			'CrossClockAnalysis': self.Host.PoCConfig[netlist.ConfigSectionName]            ['XSTOption.CrossClockAnalysis'],
			'HierarchySeparator': self.Host.PoCConfig[netlist.ConfigSectionName]            ['XSTOption.HierarchySeparator'],
			'BusDelimiter': self.Host.PoCConfig[netlist.ConfigSectionName]                  ['XSTOption.BusDelimiter'],
			'Case': self.Host.PoCConfig[netlist.ConfigSectionName]                          ['XSTOption.Case'],
			'SliceUtilizationRatio': self.Host.PoCConfig[netlist.ConfigSectionName]         ['XSTOption.SliceUtilizationRatio'],
			'BRAMUtilizationRatio': self.Host.PoCConfig[netlist.ConfigSectionName]          ['XSTOption.BRAMUtilizationRatio'],
			'DSPUtilizationRatio': self.Host.PoCConfig[netlist.ConfigSectionName]           ['XSTOption.DSPUtilizationRatio'],
			'LUTCombining': self.Host.PoCConfig[netlist.ConfigSectionName]                  ['XSTOption.LUTCombining'],
			'ReduceControlSets': self.Host.PoCConfig[netlist.ConfigSectionName]             ['XSTOption.ReduceControlSets'],
			'Verilog2001': self.Host.PoCConfig[netlist.ConfigSectionName]                   ['XSTOption.Verilog2001'],
			'FSMExtract': self.Host.PoCConfig[netlist.ConfigSectionName]                    ['XSTOption.FSMExtract'],
			'FSMEncoding': self.Host.PoCConfig[netlist.ConfigSectionName]                   ['XSTOption.FSMEncoding'],
			'FSMSafeImplementation': self.Host.PoCConfig[netlist.ConfigSectionName]         ['XSTOption.FSMSafeImplementation'],
			'FSMStyle': self.Host.PoCConfig[netlist.ConfigSectionName]                      ['XSTOption.FSMStyle'],
			'RAMExtract': self.Host.PoCConfig[netlist.ConfigSectionName]                    ['XSTOption.RAMExtract'],
			'RAMStyle': self.Host.PoCConfig[netlist.ConfigSectionName]                      ['XSTOption.RAMStyle'],
			'ROMExtract': self.Host.PoCConfig[netlist.ConfigSectionName]                    ['XSTOption.ROMExtract'],
			'ROMStyle': self.Host.PoCConfig[netlist.ConfigSectionName]                      ['XSTOption.ROMStyle'],
			'MUXExtract': self.Host.PoCConfig[netlist.ConfigSectionName]                    ['XSTOption.MUXExtract'],
			'MUXStyle': self.Host.PoCConfig[netlist.ConfigSectionName]                      ['XSTOption.MUXStyle'],
			'DecoderExtract': self.Host.PoCConfig[netlist.ConfigSectionName]                ['XSTOption.DecoderExtract'],
			'PriorityExtract': self.Host.PoCConfig[netlist.ConfigSectionName]               ['XSTOption.PriorityExtract'],
			'ShRegExtract': self.Host.PoCConfig[netlist.ConfigSectionName]                  ['XSTOption.ShRegExtract'],
			'ShiftExtract': self.Host.PoCConfig[netlist.ConfigSectionName]                  ['XSTOption.ShiftExtract'],
			'XorCollapse': self.Host.PoCConfig[netlist.ConfigSectionName]                   ['XSTOption.XorCollapse'],
			'AutoBRAMPacking': self.Host.PoCConfig[netlist.ConfigSectionName]               ['XSTOption.AutoBRAMPacking'],
			'ResourceSharing': self.Host.PoCConfig[netlist.ConfigSectionName]               ['XSTOption.ResourceSharing'],
			'ASyncToSync': self.Host.PoCConfig[netlist.ConfigSectionName]                   ['XSTOption.ASyncToSync'],
			'UseDSP48': self.Host.PoCConfig[netlist.ConfigSectionName]                      ['XSTOption.UseDSP48'],
			'IOBuf': self.Host.PoCConfig[netlist.ConfigSectionName]                         ['XSTOption.IOBuf'],
			'MaxFanOut': self.Host.PoCConfig[netlist.ConfigSectionName]                     ['XSTOption.MaxFanOut'],
			'BufG': self.Host.PoCConfig[netlist.ConfigSectionName]                          ['XSTOption.BufG'],
			'RegisterDuplication': self.Host.PoCConfig[netlist.ConfigSectionName]           ['XSTOption.RegisterDuplication'],
			'RegisterBalancing': self.Host.PoCConfig[netlist.ConfigSectionName]             ['XSTOption.RegisterBalancing'],
			'SlicePacking': self.Host.PoCConfig[netlist.ConfigSectionName]                  ['XSTOption.SlicePacking'],
			'OptimizePrimitives': self.Host.PoCConfig[netlist.ConfigSectionName]            ['XSTOption.OptimizePrimitives'],
			'UseClockEnable': self.Host.PoCConfig[netlist.ConfigSectionName]                ['XSTOption.UseClockEnable'],
			'UseSyncSet': self.Host.PoCConfig[netlist.ConfigSectionName]                    ['XSTOption.UseSyncSet'],
			'UseSyncReset': self.Host.PoCConfig[netlist.ConfigSectionName]                  ['XSTOption.UseSyncReset'],
			'PackIORegistersIntoIOBs': self.Host.PoCConfig[netlist.ConfigSectionName]       ['XSTOption.PackIORegistersIntoIOBs'],
			'EquivalentRegisterRemoval': self.Host.PoCConfig[netlist.ConfigSectionName]     ['XSTOption.EquivalentRegisterRemoval'],
			'SliceUtilizationRatioMaxMargin': self.Host.PoCConfig[netlist.ConfigSectionName]['XSTOption.SliceUtilizationRatioMaxMargin']
		}

		xstFileContent = xstFileContent.format(**xstTemplateDictionary)

		if (self.Host.PoCConfig.has_option(netlist.ConfigSectionName, 'XSTOption.Generics')):
			xstFileContent += "-generics {{ {0} }}".format(self.Host.PoCConfig[netlist.ConfigSectionName]['XSTOption.Generics'])

		self._LogDebug("Writing Xilinx Compiler Tool option file to '{0!s}'".format(netlist.XstFile))
		with netlist.XstFile.open('w') as fileHandle:
			fileHandle.write(xstFileContent)
