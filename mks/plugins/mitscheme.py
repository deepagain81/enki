import os.path

from PyQt4.QtCore import QObject, Qt, QTimer
from PyQt4.QtGui import QFileDialog, QIcon, QMessageBox, QWidget
from PyQt4 import uic

from mks.core.core import core, DATA_FILES_PATH

from PyQt4.fresh import pDockWidget

import mks.lib.buffpopen
import mks.lib.termwidget
import mks.lib.highlighter

from mks.core.uisettings import ModuleConfigurator, ChoiseOption, TextOption

#
# Integration with the core
#

class MitSchemeSettings(QWidget):
    def __init__(self, *args):
        QWidget.__init__(self, *args)
        uic.loadUi(os.path.join(DATA_FILES_PATH,'ui/plugins/MitSchemeSettings.ui'), self)
        self.pbInterpreterPath.clicked.connect(self._onPbInterpreterPathClicked)
    
    def _onPbInterpreterPathClicked(self):
        path = 	QFileDialog.getOpenFileName(core.mainWindow(), 'MIT Scheme interpreter path')
        if path:
            self.leInterpreterPath.setText(path)

class Configurator(ModuleConfigurator):
    """ Module configurator.
    
    Used to configure associations on the settings dialogue
    """
    def __init__(self, dialog):
        ModuleConfigurator.__init__(self, dialog)
        
        widget = MitSchemeSettings(dialog)
        dialog.appendPage(u"Modes/MIT Scheme", widget, QIcon(':/mksicons/languages/scheme.png'))

        # Options
        self._options = [ ChoiseOption(dialog, core.config(), "Modes/Scheme/Enabled",
                                       {widget.rbWhenOpened: "whenOpened",
                                        widget.rbNever: "never",
                                        widget.rbAlways: "always"}),
                          TextOption(dialog, core.config(), "Modes/Scheme/InterpreterPath", widget.leInterpreterPath)
                        ]
    
    def saveSettings(self):
        """Settings are stored in the core configuration file, therefore nothing to do here.
        
        Called by :mod:`mks.core.uisettings`
        """
        pass
    
    def applySettings(self):
        """Apply associations to opened documents.
        
        Called by :mod:`mks.core.uisettings`
        """
        Plugin.instance.applySettings()


class Plugin(QObject):
    """Module implementation
    """
    
    instance = None
    
    def __init__(self):
        QObject.__init__(self)
        self._installed = False
        self._evalAction = None
        self._activeInterpreterPath = None

        self._schemeDocumentsCount = 0
        
        for doc in core.workspace().openedDocuments():
            self._schemeDocumentsCount += 1
        
        # TODO handle situation, when lexer changed for current document
        core.workspace().documentOpened.connect(self._onDocumentOpened)
        core.workspace().documentClosed.connect(self._onDocumentClosed)
        core.workspace().currentDocumentChanged.connect(self._updateEvalActionEnabledState)
        
        self._installOrUninstallIfNecessary()
        Plugin.instance = self

    def __del__(self):
        self.uninstall()
        Plugin.instance = None

    def moduleConfiguratorClass(self):
        """ ::class:`mks.core.uisettings.ModuleConfigurator` used to configure plugin with UISettings dialogue
        """
        return Configurator

    def applySettings(self):
        """Apply settings. Called by configurator class
        """
        # if path has been changed - restart the interpreter
        if self._installed and \
           self._activeInterpreterPath != core.config()["Modes"]["Scheme"]["InterpreterPath"]:
            self.uninstall()
        
        self._installOrUninstallIfNecessary()

    def _isSchemeFile(self, document):
        return document is not None and \
               document.highlightingLanguage() == 'Scheme'

    def _onDocumentOpened(self, document):
        document.languageChanged.connect(self._onDocumentLanguageChanged)

        if self._isSchemeFile(document):
            self._schemeDocumentsCount += 1
            self._installOrUninstallIfNecessary()

    def _onDocumentClosed(self, document):
        if self._isSchemeFile(document):
            self._schemeDocumentsCount -= 1
            self._installOrUninstallIfNecessary()
    
    def _onDocumentLanguageChanged(self, old, new):
        if old is not None and old == 'Scheme':
            self._schemeDocumentsCount -= 1
        if new is not None and new == 'Scheme':
            self._schemeDocumentsCount += 1
        self._installOrUninstallIfNecessary()
        self._updateEvalActionEnabledState()

    def _updateEvalActionEnabledState(self):
        if self._evalAction is None:
            return

        currDoc = core.workspace().currentDocument()
        self._evalAction.setEnabled(currDoc is not None and self._isSchemeFile(currDoc))

    def _installOrUninstallIfNecessary(self):
        enabled =  core.config()["Modes"]["Scheme"]["Enabled"]
        if enabled == 'always':
            if not self._installed:
                self._install()
        elif enabled == 'never':
            if self._installed:
                self.uninstall()
        else:
            assert enabled == 'whenOpened'
            if self._schemeDocumentsCount > 0:
                self._install()
            else:
                self.uninstall()

    def _install(self):
        if self._installed:
            return

        self._schemeMenu = core.actionModel().addMenu("mScheme", "MIT Scheme")
        self._evalAction = core.actionModel().addAction("mScheme/mEval", "Eval. selection/Save and eval.")
        self._evalAction.setStatusTip("Evaluate selection. If nothing is selected - save and evaluate whole file")
        self._evalAction.setShortcut("Ctrl+E")
        self._evalAction.triggered.connect(self._onEvalTriggered)
        self._updateEvalActionEnabledState()

        self._activeInterpreterPath = core.config()["Modes"]["Scheme"]["InterpreterPath"]
        self._mitScheme = MitScheme(self._activeInterpreterPath)
        self._dock = MitSchemeDock(self._mitScheme.widget())

        core.mainWindow().dockToolBar( Qt.BottomToolBarArea ).addDockWidget(self._dock)

        self._installed = True
    
    def uninstall(self):
        """Terminate the plugin. Method called by core, when closing mksv3, and sometimes by plugin itself
        """
        if not self._installed:
            return
        core.actionModel().removeAction("mScheme/mEval")
        self._evalAction = None
        core.actionModel().removeMenu("mScheme")
        self._mitScheme.stop()
        core.mainWindow().dockToolBar( Qt.BottomToolBarArea ).removeDockWidget(self._dock)
        del self._dock
        self._installed = False

    def _onEvalTriggered(self):
        document = core.workspace().currentDocument()
        if document is None:
            return
        
        selection = document.selectedText()
        if selection:
            self._mitScheme.execCommand(selection)
        else:
            if document.isModified():
                document.saveFile()
            self._mitScheme.loadFile(document.filePath())

class MitSchemeDock(pDockWidget):
    def __init__(self, widget):
        pDockWidget.__init__(self, "MIT Scheme", core.mainWindow())
        self.setObjectName("MitSchemeDock")
        self.setWindowIcon(QIcon(':/mksicons/languages/scheme.png'))
        self.setAllowedAreas( Qt.BottomDockWidgetArea)
        
        self.showAction().setShortcut("F8")
        core.actionModel().addAction("mDocks/aMitScheme", self.showAction())

        self.setWidget(widget)
        self.setFocusProxy(widget)

    def __del__(self):
        core.actionModel().removeAction("mDocks/aMitScheme")

#
# Plugin functionality
#

class MitSchemeTermWidget(mks.lib.termwidget.TermWidget):
    def __init__(self, mitScheme, *args):
        mks.lib.termwidget.TermWidget.__init__(self, *args)
        self._mitScheme = mitScheme
        self._hl = mks.lib.highlighter.Highlighter(self._edit)

    def isCommandComplete(self, text):
        # TODO support comments
        # Stage 1: remove strings
        index = 0
        foundStrings = []
        while True:
            try:
                index = text.index('"', index)
            except ValueError:
                break;
            
            try:
                endIndex = text.index('"', index + 1)
            except ValueError:
                return False

            foundStrings.append((index, endIndex))
            index = endIndex + 1

        for foundString in foundStrings[::-1]:  # from the last found string
            text = text[:foundString[0]] + text[foundString[1] + 1:]  # remove found string
        
        # Stage 2: calculate braces
        # Let's MIT scheme check if braces are placed correctly. We just check count
        if text.count('(') != text.count(')'):
            return False
        
        return True

    def childExecCommand(self, text):
        self._mitScheme.execCommand(text)

class MitScheme:
    """MIT scheme shell. Implements REPL. Graphical frontend for original terminal version.
    """
    def __init__(self, interpreterPath):
        self._term = MitSchemeTermWidget(self)
        self._interpreterPath = interpreterPath
        
        self._processOutputTimer = QTimer()  # I use Qt timer, because we must append data to GUI in the GUI thread
        self._processOutputTimer.timeout.connect(self._processOutput)
        self._processOutputTimer.setInterval(100)

        self._buffPopen = mks.lib.buffpopen.BufferedPopen(interpreterPath)
        self._schemeIsRunning = False
        
        self._term.appendOutput("Execute any command to run the scheme interpreter\n")

    def __del__(self):
        self.stop()
    
    def widget(self):
        return self._term

    def start(self):
        try:
            self._buffPopen.start()
        except OSError, ex:
            text = '<p>Interpreter path: %s</p>' % self._interpreterPath
            text += '<p>Error: %s</p>' % unicode(str(ex), 'utf8')
            text += '<p>Make sure MIT Scheme is installed and go to '\
                    '<b>Settings -> Settings -> Modes -> MIT&nbsp;Scheme</b> to correct the path</p>'
            text = '<html>%s</html' % text
            QMessageBox.critical (core.mainWindow(),
                                  "Failed to run MIT Scheme", 
                                  text)
            raise UserWarning("Failed to run the interpreter")

        self._processOutputTimer.start()
        self._schemeIsRunning = True

    def stop(self):
        self._processOutputTimer.stop()
        self._buffPopen.stop()
        self._schemeIsRunning = False

    def execCommand(self, text):
        if not self._schemeIsRunning:
            try:
                self.start()
            except UserWarning:
                return

        self._processOutput() # write old output to the log, and only then write fresh input
        self._buffPopen.write(text)
    
    def loadFile(self, filePath):
        """Load file using MIT Scheme load function
        """
        if not self._schemeIsRunning:
            try:
                self.start()
            except UserWarning:
                return
        self._buffPopen.write('(load "%s")' % filePath)
    
    def _processOutput(self):
        output = self._buffPopen.readOutput()
        if output:
            self._term.appendOutput(output)
        if self._schemeIsRunning and not self._buffPopen.isAlive():
            self._term.appendError("Interpreter process exited. Execute any command to run it again\n")
            self.stop()
