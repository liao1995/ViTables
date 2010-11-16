# -*- coding: utf-8 -*-
#!/usr/bin/env python

#       Copyright (C) 2005-2007 Carabos Coop. V. All rights reserved
#       Copyright (C) 2008-2010 Vicent Mas. All rights reserved
#
#       This program is free software: you can redistribute it and/or modify
#       it under the terms of the GNU General Public License as published by
#       the Free Software Foundation, either version 3 of the License, or
#       (at your option) any later version.
#
#       This program is distributed in the hope that it will be useful,
#       but WITHOUT ANY WARRANTY; without even the implied warranty of
#       MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#       GNU General Public License for more details.
#
#       You should have received a copy of the GNU General Public License
#       along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#       Author:  Vicent Mas - vmas@vitables.org

"""Here is defined the VTApp class."""

__docformat__ = 'restructuredtext'
_context = 'VTApp'

import os
import time
import re
import sys

import tables

from PyQt4 import QtCore, QtGui

import vitables.utils
import vitables.logger as logger
import vitables.vtsplash
from vitables.vtSite import ICONDIR

from  vitables.preferences import vtconfig
import vitables.preferences.pluginsLoader as pluginsLoader
from  vitables.preferences import preferences

import vitables.h5db.dbsTreeModel as dbsTreeModel
import vitables.h5db.dbsTreeView as dbsTreeView

import vitables.queries.queriesManager as qmgr

import vitables.vtWidgets.inputNodeName as inputNodeName
import vitables.vtWidgets.renameDlg as renameDlg

import vitables.nodeProperties.nodeInfo as nodeInfo
from vitables.nodeProperties import nodePropDlg
from vitables.docBrowser import helpBrowser

import vitables.vtTables.buffer as rbuffer
import vitables.vtTables.dataSheet as dataSheet


def trs(source, comment=None):
    """Translate string function."""
    return unicode(QtGui.qApp.translate(_context, source, comment))


class VTApp(QtGui.QMainWindow):
    """
    The application core.

    It handles the user input and controls both views and documents.
    VTApp methods can be grouped as:

    * GUI initialization and configuration methods
    * slots that handle user input
    """


    leaf_model_created = QtCore.pyqtSignal(QtGui.QMdiSubWindow, \
        name="leafModelCreated")

    pluginsLoaded = QtCore.pyqtSignal()


    def __init__(self, mode='', dblist='', h5files=None, keep_splash=True):
        """
        Initialize the application.

        This method starts the application: makes the GUI, configure the
        app, instantiates managers needed to control the app. and connect
        signals to slots.

        :Parameters:

        - `mode`: the opening mode for files passed in the command line
        - `h5files`: a list of files to be open at startup
        - `dblist`: a file that contains a list of files to be open at startup
        """

        QtGui.QMainWindow.__init__(self)

        # Make the main window easily accessible for external modules
        self.setObjectName('VTApp')

        self.is_first_opening = True  # for Open file dialogs
        self.icons_dictionary = vitables.utils.getIcons()
        # Instantiate a configurator object for the application
        self.config = vtconfig.Config()

        # Show a splash screen
        logo = QtGui.QPixmap(os.path.join(ICONDIR, "vitables_logo.png"))
        splash = vitables.vtsplash.VTSplash(logo)
        splash.show()
        t_i = time.time()

        #
        # Make the GUI
        #
        splash.drawMessage(trs('Creating the GUI...',
            'A splash screen message'))
        self.setWindowTitle(trs('ViTables %s' % vtconfig.getVersion(),
            'Main window title'))
        self.setIconSize(QtCore.QSize(22, 22))
        self.setWindowIcon(self.icons_dictionary['vitables_wm'])
        central_widget = QtGui.QWidget(self)
        central_layout = QtGui.QVBoxLayout(central_widget)
        self.vsplitter = QtGui.QSplitter(QtCore.Qt.Vertical, central_widget)
        central_layout.addWidget(self.vsplitter)
        self.setCentralWidget(central_widget)

        # Divide the top region of the window into 2 regions and put there
        # the tree of databases and the workspace
        self.hsplitter = QtGui.QSplitter(self.vsplitter)
        self.dbs_tree_model = dbsTreeModel.DBsTreeModel(self)
        self.dbs_tree_view = dbsTreeView.DBsTreeView(self.dbs_tree_model, 
            self.hsplitter)
        self.workspace = QtGui.QMdiArea(self.hsplitter)
        sb_as_needed = QtCore.Qt.ScrollBarAsNeeded
        self.workspace.setHorizontalScrollBarPolicy(sb_as_needed)
        self.workspace.setVerticalScrollBarPolicy(sb_as_needed)
        self.workspace.setWhatsThis(trs(
            """<qt>
            <h3>The Workspace</h3>
            This is the area where open leaves of the object tree are
            displayed. Many tables and arrays can be displayed
            simultaneously.
            <p>The diferent views can be tiled as a mosaic or stacked as
            a cascade.
            </qt>""",
            'WhatsThis help for the workspace')
            )

        # Put the logging console in the bottom region of the window
        self.logger = logger.Logger(self.vsplitter)

        # The queries manager
        self.queries_mgr = qmgr.QueriesManager()

        # The signal mapper used to keep the the Windows menu updated
        self.window_mapper = QtCore.QSignalMapper(self)
        self.window_mapper.mapped[QtGui.QWidget].connect(\
            self.workspace.setActiveSubWindow)

        self.gui_actions = self.setupActions()
        self.setupToolBars()
        self.setupMenus()
        self.initStatusBar()
        self.logger.nodeCopyAction = self.gui_actions['nodeCopy']

        # Redirect standard output and standard error to a Logger instance
        sys.stdout = self.logger
        sys.stderr = self.logger

        # Apply the configuration stored on disk
        splash.drawMessage(trs('Configuration setup...',
            'A splash screen message'))
        self.config.loadConfiguration(self.config.readConfiguration())

        # Print the welcome message
        print trs('''ViTables %s\nCopyright (c) 2008-2010 Vicent Mas.'''
            '''\nAll rights reserved.''' % vtconfig.getVersion(),
            'Application startup message')

        # The list of most recently open DBs
        self.number_of_recent_files = 10
        while self.config.recent_files.count() > self.number_of_recent_files:
            self.config.recent_files.takeLast()

        # The File Selector History
        self.file_selector_history = QtCore.QStringList()
        if self.config.startup_working_directory != u'last':
            self.config.last_working_directory = os.getcwdu()
        self.file_selector_history.append(self.config.last_working_directory)

        # List of HelpBrowser instances in memory
        self.doc_browser = None

        # Load plugins.
        # Some plugins modify existing menus so plugins must be loaded after
        # creating the user interface.
        # Some plugins modify datasets displaying so plugins must be loaded
        # before opening any file.
        self.plugins_mgr = \
            pluginsLoader.PluginsLoader(self.config.plugins_paths, 
            self.config.enabled_plugins)
        self.plugins_mgr.loadAll()
        self.pluginsLoaded.emit()

        # Restore last session
        if self.config.restore_last_session:
            splash.drawMessage(trs('Recovering last session...',
                'A splash screen message'))
            self.recoverLastSession()

        # Process the command line
        if h5files:
            splash.drawMessage(trs('Opening files...',
                'A splash screen message'))
            self.processCommandLineArgs(mode=mode, h5files=h5files)
        elif dblist:
            splash.drawMessage(trs('Opening the list of files...',
                'A splash screen message'))
            self.processCommandLineArgs(dblist=dblist)

        # Make sure that the splash screen is shown at least for two seconds
        if keep_splash:
            t_f = time.time()
            while t_f - t_i < 2:
                t_f = time.time()
        splash.finish(self)
        del splash

        # Ensure that QActions have a consistent state
        self.updateActions()

        self.dbs_tree_model.rowsRemoved.connect(self.updateActions)
        self.dbs_tree_model.rowsInserted.connect(self.updateActions)

        self.updateWindowsMenu()

        self.workspace.installEventFilter(self)


    def setupActions(self):
        """Provide actions to the menubar and the toolbars.
        """

        # Setting action names makes it easier to acces this actions
        # from plugins
        actions = {}
        actions['fileNew'] = vitables.utils.createAction(self, 
            trs('&New', 'File -> New'), QtGui.QKeySequence.New, 
            self.fileNew, self.icons_dictionary['document-new'], 
            trs('Create a new file', 
                'Status bar text for the File -> New action'))
        actions['fileNew'].setObjectName('fileNew')

        actions['fileOpen'] = vitables.utils.createAction(self, 
            trs('&Open...', 'File -> Open'), QtGui.QKeySequence.Open, 
            self.fileOpen, self.icons_dictionary['document-open'], 
            trs('Open an existing file',
                'Status bar text for the File -> Open action'))
        actions['fileOpen'].setObjectName('fileOpen')

        actions['fileOpenRO'] = vitables.utils.createAction(self, 
            trs('Read-only open...', 'File -> Open'), None, 
            self.fileOpenRO, self.icons_dictionary['document-open'], 
            trs('Open an existing file in read-only mode',
                'Status bar text for the File -> Open action'))
        actions['fileOpenRO'].setObjectName('fileOpenRO')

        actions['fileClose'] = vitables.utils.createAction(self, 
            trs('&Close', 'File -> Close'), QtGui.QKeySequence.Close, 
            self.fileClose, self.icons_dictionary['document-close'], 
            trs('Close the selected file',
                'Status bar text for the File -> Close action'))
        actions['fileClose'].setObjectName('fileClose')

        actions['fileCloseAll'] = vitables.utils.createAction(self, 
            trs('Close &All', 'File -> Close All'), None, 
            self.fileCloseAll, None, 
            trs('Close all files',
                'Status bar text for the File -> Close All action'))
        actions['fileCloseAll'].setObjectName('fileCloseAll')

        actions['fileSaveAs'] = vitables.utils.createAction(self, 
            trs('&Save as...', 'File -> Save As'), 
            QtGui.QKeySequence('CTRL+SHIFT+S'), 
            self.fileSaveAs, self.icons_dictionary['document-save-as'], 
            trs('Save a renamed copy of the selected file',
                'Status bar text for the File -> Save As action'))
        actions['fileSaveAs'].setObjectName('fileSaveAs')

        actions['fileExit'] = vitables.utils.createAction(self, 
            trs('E&xit', 'File -> Exit'), QtGui.QKeySequence('CTRL+Q'), 
            self.fileExit, self.icons_dictionary['application-exit'], 
            trs('Quit ViTables',
                'Status bar text for the File -> Exit action'))
        actions['fileExit'].setObjectName('fileExit')

        actions['nodeOpen'] = vitables.utils.createAction(self, 
            trs('&Open view', 'Node -> Open View'), 
            QtGui.QKeySequence('CTRL+SHIFT+O'), 
            self.nodeOpen, None, 
            trs('Display the contents of the selected node', 
                'Status bar text for the Node -> Open View action'))
        actions['nodeOpen'].setObjectName('nodeOpen')

        actions['nodeClose'] = vitables.utils.createAction(self, 
            trs('C&lose view', 'Node -> Close View'), 
            QtGui.QKeySequence('CTRL+SHIFT+W'), 
            self.nodeClose, None, 
            trs('Close the view of the selected node', 
                'Status bar text for the Node -> Close View action'))
        actions['nodeClose'].setObjectName('nodeClose')

        actions['nodeProperties'] = vitables.utils.createAction(self, 
            trs('Prop&erties...', 'Node -> Properties'), 
            QtGui.QKeySequence('CTRL+I'), 
            self.nodeProperties, self.icons_dictionary['help-about'], 
            trs('Show the properties dialog for the selected node', 
                'Status bar text for the Node -> Properties action'))
        actions['nodeProperties'].setObjectName('nodeProperties')

        actions['nodeNew'] = vitables.utils.createAction(self, 
            trs('&New group...', 'Node -> New group'), 
            QtGui.QKeySequence('CTRL+SHIFT+N'), 
            self.nodeNewGroup, self.icons_dictionary['folder-new'], 
            trs('Create a new group under the selected node', 
                'Status bar text for the Node -> New group action'))
        actions['nodeNew'].setObjectName('nodeNew')

        actions['nodeRename'] = vitables.utils.createAction(self, 
            trs('&Rename...', 'Node -> Rename'), 
            QtGui.QKeySequence('CTRL+R'), 
            self.nodeRename, self.icons_dictionary['edit-rename'], 
            trs('Rename the selected node', 
                'Status bar text for the Node -> Rename action'))
        actions['nodeRename'].setObjectName('nodeRename')

        actions['nodeCut'] = vitables.utils.createAction(self, 
            trs('Cu&t', 'Node -> Cut'), QtGui.QKeySequence('CTRL+X'), 
            self.nodeCut, self.icons_dictionary['edit-cut'], 
            trs('Cut the selected node', 
                'Status bar text for the Node -> Cut action'))
        actions['nodeCut'].setObjectName('nodeCut')

        actions['nodeCopy'] = vitables.utils.createAction(self, 
            trs('&Copy', 'Node -> Copy'), QtGui.QKeySequence.Copy, 
            self.makeCopy, self.icons_dictionary['edit-copy'], 
            trs('Copy the selected node', 
                'Status bar text for the Node -> Copy action'))
        actions['nodeCopy'].setObjectName('nodeCopy')

        actions['nodePaste'] = vitables.utils.createAction(self, 
            trs('&Paste', 'Node -> Paste'), QtGui.QKeySequence.Paste, 
            self.nodePaste, self.icons_dictionary['edit-paste'], 
            trs('Paste the last copied/cut node', 
                'Status bar text for the Node -> Copy action'))
        actions['nodePaste'].setObjectName('nodePaste')

        actions['nodeDelete'] = vitables.utils.createAction(self, 
            trs('&Delete', 'Node -> Delete'), QtGui.QKeySequence.Delete, 
            self.nodeDelete, self.icons_dictionary['edit-delete'], 
            trs('Delete the selected node', 
                'Status bar text for the Node -> Copy action'))
        actions['nodeDelete'].setObjectName('nodeDelete')

        actions['queryNew'] = vitables.utils.createAction(self, 
            trs('&Query...', 'Query -> New...'), None, 
            self.queries_mgr.newQuery, self.icons_dictionary['view-filter'], 
            trs('Create a new filter for the selected table', 
                'Status bar text for the Query -> New... action'))
        actions['queryNew'].setObjectName('queryNew')

        actions['queryDeleteAll'] = vitables.utils.createAction(self, 
            trs('Delete &All', 'Query -> Delete All'), None, 
            self.queries_mgr.deleteAllQueries, 
            self.icons_dictionary['delete_filters'], 
            trs('Remove all filters', 
                'Status bar text for the Query -> Delete All action'))
        actions['queryDeleteAll'].setObjectName('queryDeleteAll')

        actions['settingsPreferences'] = vitables.utils.createAction(self, 
            trs('&Preferences...', 'Settings -> Preferences'), None, 
            self.settingsPreferences, 
            self.icons_dictionary['configure'], 
            trs('Configure ViTables', 
                'Status bar text for the Settings -> Preferences action'))
        actions['settingsPreferences'].setObjectName('settingsPreferences')

        actions['windowCascade'] = vitables.utils.createAction(self, 
            trs('&Cascade', 'Windows -> Cascade'), None, 
            self.workspace.cascadeSubWindows, None, 
            trs('Arranges open windows in a cascade pattern', 
                'Status bar text for the Windows -> Cascade action'))
        actions['windowCascade'].setObjectName('windowCascade')

        actions['windowTile'] = vitables.utils.createAction(self, 
            trs('&Tile', 'Windows -> Tile'), None, 
            self.workspace.tileSubWindows, None, 
            trs('Arranges open windows in a tile pattern', 
                'Status bar text for the Windows -> Tile action'))
        actions['windowTile'].setObjectName('windowTile')

        actions['windowRestoreAll'] = vitables.utils.createAction(self, 
            trs('&Restore All', 'Windows -> Restore All'), None, 
            self.windowsRestoreAll, None, 
            trs('Restore all minimized windows on the workspace', 
                'Status bar text for the Windows -> Restore All action'))
        actions['windowRestoreAll'].setObjectName('windowRestoreAll')

        actions['windowMinimizeAll'] = vitables.utils.createAction(self, 
            trs('&Minimize All', 'Windows -> Minimize All'), None, 
            self.windowsMinimizeAll, None, 
            trs('Minimize all windows on the workspace', 
                'Status bar text for the Windows -> Restore All action'))
        actions['windowMinimizeAll'].setObjectName('windowMinimizeAll')

        actions['windowClose'] = vitables.utils.createAction(self, 
            trs('C&lose', 'Windows -> Close'), None, 
            self.windowsClose, None, 
            trs('Close the active view', 
                'Status bar text for the Windows -> Close action'))
        actions['windowClose'].setObjectName('windowClose')

        actions['windowCloseAll'] = vitables.utils.createAction(self, 
            trs('Close &All', 'Windows -> Close All'), None, 
            self.windowsCloseAll, None, 
            trs('Close all views', 
                'Status bar text for the Windows -> Close All action'))
        actions['windowCloseAll'].setObjectName('windowCloseAll')

        actions['windowsActionGroup'] = QtGui.QActionGroup(self)

        actions['mdiTabbed'] = vitables.utils.createAction(self, 
            trs('Change view mode', 'MDI -> Tabbed'), None, 
            self.changeMDIViewMode, 
            None, 
            trs('Change the workspace view mode', 
                'Status bar text for the MDI -> Tabbed action'))
        actions['mdiTabbed'].setObjectName('mdiTabbed')

        actions['helpUsersGuide'] = vitables.utils.createAction(self, 
            trs("&User's Guide", 'Help -> Users Guide'), 
            QtGui.QKeySequence.HelpContents, 
            self.helpBrowser, 
            self.icons_dictionary['help-contents'], 
            trs("Open the ViTables User's Guide",
                    'Status bar text for the Help -> Users Guide action'))
        actions['helpUsersGuide'].setObjectName('helpUsersGuide')

        actions['helpAbout'] = vitables.utils.createAction(self, 
            trs('&About ViTables', 'Help -> About'), None, 
            self.helpAbout, 
            self.icons_dictionary['vitables_wm'], 
            trs('Display information about ViTables',
                    'Status bar text for the Help -> About action'))
        actions['helpAbout'].setObjectName('helpAbout')

        actions['helpAboutQt'] = vitables.utils.createAction(self, 
            trs('About &Qt', 'Help -> About Qt'), None, 
            self.helpAboutQt, None, 
            trs('Display information about the Qt library',
                    'Status bar text for the Help -> About Qt action'))
        actions['helpAboutQt'].setObjectName('helpAboutQt')

        actions['helpVersions'] = vitables.utils.createAction(self, 
            trs('Show &Versions', 'Help -> Show Versions'), None, 
            self.helpVersions, None, 
            trs('Show the versions of the libraries used by ViTables',
                    'Status bar text for the Help -> Show Versions action'))
        actions['helpVersions'].setObjectName('helpVersions')

        return actions


    def setupToolBars(self):
        """
        Set up the main window toolbars.

        Toolbars are made of actions.
        """

        # File toolbar
        self.file_toolbar = self.addToolBar(trs('File operations', 
            'Toolbar title'))
        # Warning! Do NOT use 'File toolbar' as a object name or it will
        # show an strange behaviour (a Qt bug I think): it will always
        # be added to the left and will expand the whole top area
        self.file_toolbar.setObjectName('File')
        actions = ['fileNew', 'fileOpen', 'fileClose', 'fileSaveAs', 
                   'fileExit']
        vitables.utils.addActions(self.file_toolbar, actions, self.gui_actions)

        # Reset the tooltip of the File -> Open... button
        file_open_button = self.file_toolbar.widgetForAction(
            self.gui_actions['fileOpen'])
        file_open_button.setToolTip(trs("""Click to open a """
            """file\nClick and hold to open a recent file""",
            'File toolbar -> Open Recent Files'))

        # Node toolbar
        self.node_toolbar = self.addToolBar(trs('Node operations', 
            'Toolbar title'))
        self.node_toolbar.setObjectName('Node toolbar')
        actions = ['nodeNew', 'nodeCut', 'nodeCopy', 'nodePaste', 'nodeDelete']
        vitables.utils.addActions(self.node_toolbar, actions, self.gui_actions)

        # Query toolbar
        self.query_toolbar = self.addToolBar(trs('Queries on tables', 
            'Toolbar title'))
        self.query_toolbar.setObjectName('Query toolbar')
        actions = ['queryNew', 'queryDeleteAll']
        vitables.utils.addActions(self.query_toolbar, actions, 
                                    self.gui_actions)

        # Help toolbar
        self.help_toolbar = self.addToolBar(trs('Help system', 
            'Toolbar title'))
        self.help_toolbar.setObjectName('Help toolbar')
        actions = ['helpUsersGuide']
        vitables.utils.addActions(self.help_toolbar, actions, self.gui_actions)
        whatis = QtGui.QWhatsThis.createAction(self.help_toolbar)
        whatis.setStatusTip(trs('Contextual help',
                    'Status bar text for the Help -> Whats This action'))
        self.help_toolbar.addAction(whatis)


    def setupMenus(self):
        """
        Set up the main window menus.

        Popus are made of actions, items and separators.
        The Window menu is a special case due to its dynamic nature. Its
        contents depend on the number of existing views.
        In order to track changes and keep updated the menu, it is reloaded
        every time it is about to be displayed. This goal is achieved using
        signal/slot mechanism (see code below).
        """

        # Create the File menu and add actions/submenus/separators to it
        self.file_menu = self.menuBar().addMenu(trs("&File", 
            'The File menu entry'))
        self.file_menu.setObjectName('file_menu')
        self.open_recent_submenu = QtGui.QMenu(trs('Open R&ecent Files',
            'File -> Open Recent Files'))
        self.open_recent_submenu.setObjectName('open_recent_submenu')
        self.open_recent_submenu.setSeparatorsCollapsible(False)
        self.open_recent_submenu.setIcon(\
            self.icons_dictionary['document-open-recent'])
        file_actions = ['fileNew', 'fileOpen', 'fileOpenRO', 
            self.open_recent_submenu, None, 'fileClose', 'fileCloseAll', None, 
            'fileSaveAs', None, 'fileExit']
        vitables.utils.addActions(self.file_menu, file_actions, 
            self.gui_actions)

        file_open_button = self.file_toolbar.widgetForAction(
            self.gui_actions['fileOpen'])
        file_open_button.setMenu(self.open_recent_submenu)
        self.open_recent_submenu.aboutToShow.connect(\
            self.updateRecentSubmenu)

        # Create the Node menu and add actions/submenus/separators to it
        node_menu = self.menuBar().addMenu(trs("&Node", 
            'The Node menu entry'))
        node_menu.setObjectName('node_menu')
        node_actions = ['nodeOpen', 'nodeClose', 'nodeProperties', None, 
            'nodeNew', 'nodeRename', 'nodeCut', 'nodeCopy', 'nodePaste', 
            'nodeDelete']
        vitables.utils.addActions(node_menu, node_actions, self.gui_actions)

        # Create the Dataset menu and add actions/submenus/separators to it
        self.dataset_menu = self.menuBar().addMenu(trs("&Dataset", 
            'The Dataset menu entry'))
        self.dataset_menu.setObjectName('dataset_menu')
        dataset_actions = ['queryNew', None]
        vitables.utils.addActions(self.dataset_menu, dataset_actions, 
            self.gui_actions)

        # Create the Settings menu and add actions/submenus/separators to it
        settings_menu = self.menuBar().addMenu(trs("&Settings", 
            'The Settings menu entry'))
        settings_menu.setObjectName('settings-menu')
        self.hide_toolbar_submenu = self.createPopupMenu()
        self.hide_toolbar_submenu.menuAction().setText(trs('ToolBars', 
                                                'Tools -> ToolBars action'))
        settings_actions = ['settingsPreferences', None, 
            self.hide_toolbar_submenu]
        vitables.utils.addActions(settings_menu, settings_actions, 
            self.gui_actions)

        # Create the Window menu and add actions/menus/separators to it
        self.windows_menu = self.menuBar().addMenu(trs("&Window", 
            'The Windows menu entry'))
        self.windows_menu.setObjectName('windows_menu')
        action_group = QtGui.QActionGroup(self.windows_menu)
        action_group.setExclusive(True)
        self.windows_menu.action_group = action_group
        self.windows_menu.aboutToShow.connect(self.updateWindowsMenu)

        # Create the Help menu and add actions/menus/separators to it
        help_menu = self.menuBar().addMenu(trs("&Help", 
            'The Help menu entry'))
        help_menu.setObjectName('help_menu')
        help_actions = ['helpUsersGuide', None, 'helpAbout', 'helpAboutQt', 
            'helpVersions', None]
        vitables.utils.addActions(help_menu, help_actions, self.gui_actions)
        whatis = QtGui.QWhatsThis.createAction(help_menu)
        whatis.setStatusTip(trs('Context help',
                    'Status bar text for the Help -> Whats This action'))
        help_menu.addAction(whatis)

        #########################################################
        #
        # 				Context menus
        #
        #########################################################

        self.view_cm = QtGui.QMenu()
        actions = ['fileNew', 'fileOpen', 'fileOpenRO', 
            self.open_recent_submenu, None, 'fileClose', 'fileCloseAll', None, 
            'fileSaveAs', None, 'fileExit']
        vitables.utils.addActions(self.view_cm, actions, self.gui_actions)

        self.root_node_cm = QtGui.QMenu()
        actions = ['fileClose', 'fileSaveAs', None, 'nodeProperties', None, 
            'nodeNew', 'nodeCopy', 'nodePaste', None, 'queryDeleteAll']
        vitables.utils.addActions(self.root_node_cm, actions, self.gui_actions)

        self.group_node_cm = QtGui.QMenu()
        actions = ['nodeProperties', None, 'nodeNew', 'nodeRename', 'nodeCut', 
            'nodeCopy', 'nodePaste', 'nodeDelete']
        vitables.utils.addActions(self.group_node_cm, actions, 
                                    self.gui_actions)

        self.leaf_node_cm = QtGui.QMenu()
        actions = ['nodeOpen', 'nodeClose', None, 'nodeProperties', None, 
            'nodeRename', 'nodeCut', 'nodeCopy', 'nodePaste', 'nodeDelete', 
            None, 'queryNew']
        vitables.utils.addActions(self.leaf_node_cm, actions, self.gui_actions)

        self.mdi_cm = QtGui.QMenu()
        actions = ['mdiTabbed', None, 
            self.windows_menu]
        vitables.utils.addActions(self.mdi_cm, actions, self.gui_actions)


    def initStatusBar(self):
        """Init status bar."""

        status_bar = self.statusBar()
        self.sb_node_info = QtGui.QLabel(status_bar)
        self.sb_node_info.setSizePolicy(QtGui.QSizePolicy.MinimumExpanding, \
                                        QtGui.QSizePolicy.Minimum)
        status_bar.addPermanentWidget(self.sb_node_info)
        self.sb_node_info.setToolTip(trs(
            'The node currently selected in the Tree of databases pane',
            'The Selected node box startup message'))
        status_bar.showMessage(trs('Ready...',
            'The status bar startup message'))

    # Databases are automatically opened at startup when:
    # 
    #     * application is configured for recovering last session
    #     * ViTables is started from the command line with some args
    #

    def recoverLastSession(self):
        """
        Recover the last session.

        This method will attempt to open those files and leaf views that
        were opened the last time the user closed ViTables.
        The lists of files and leaves is read from the configuration.
        The format is::

            ['mode#@#filepath1#@#nodepath1#@#nodepath2, ...',
            'mode#@#filepath2#@#nodepath1#@#nodepath2, ...', ...]
        """

        expanded_signal = QtCore.SIGNAL("expanded(QModelIndex)")
        for file_data in self.config.session_files_nodes:
            item = unicode(file_data).split('#@#')
            # item looks like [mode, filepath1, nodepath1, nodepath2, ...]
            mode = item.pop(0)
            filepath = item.pop(0)
            filepath = vitables.utils.forwardPath(filepath)
            # Open the database --> add the root group to the tree view.
            self.dbs_tree_model.openDBDoc(filepath, mode)
            db_doc = self.dbs_tree_model.getDBDoc(filepath)
            if db_doc is None:
                continue
            # Update the history file
            self.updateRecentFiles(filepath, mode)

            # For opening a node the groups in the nodepath are expanded
            # left to right letting the lazy population feature to work
            for nodepath in item:  # '/group1/group2/...groupN/leaf'
                # Check if the node still exists because the database
                # could have changed since last ViTables session
                node = db_doc.getNode(nodepath)
                if node is None:
                    continue
                # groups is ['', 'group1', 'group2', ..., 'groupN']
                groups = nodepath.split('/')[:-1]
                # Expands the top level group, i.e., the root group.
                # It happens to be the last root node added to model
                # so its row is 0
                group = self.dbs_tree_model.root.childAtRow(0)
                index = self.dbs_tree_model.index(0, 0, QtCore.QModelIndex())
                self.dbs_tree_view.expanded.emit(index)
                groups.pop(0)
                # Expand the rest of groups of the nodepath
                while groups != []:
                    parent_group = group
                    parent_index = index
                    group = parent_group.findChild(groups[0])
                    row = group.row()
                    index = self.dbs_tree_model.index(row, 0, parent_index)
                    self.dbs_tree_view.expanded.emit(index)
                    groups.pop(0)
                # Finally we open the leaf
                leaf_name = nodepath.split('/')[-1]
                leaf = group.findChild(leaf_name)
                row = leaf.row()
                leaf_index = self.dbs_tree_model.index(row, 0, index)
                self.dbs_tree_view.setCurrentIndex(leaf_index)
                self.nodeOpen(leaf_index)


    def processCommandLineArgs(self, mode='', h5files=None, dblist=''):
        """Open files passed in the command line."""

        bad_line = trs("""Opening failed: wrong mode or path in %s""", 
                            'Bad line format')
        # The database manager opens the files (if any)
        if isinstance(h5files, list):
            for filepath in h5files:
                filepath = vitables.utils.forwardPath(filepath)
                self.dbs_tree_model.openDBDoc(filepath, mode)
                self.updateRecentFiles(filepath, mode)

        # If a list of files is passed then parse the list and open the files
        if dblist:
            try:
                input_file = open(dblist, 'r')
                lines = [l[:-1].split('#@#') for l in input_file.readlines()]
                input_file.close()
                for line in lines:
                    if len(line) !=2:
                        print bad_line % line
                        continue
                    mode, filepath = line
                    filepath = vitables.utils.forwardPath(filepath)
                    if not mode in ['r', 'a']:
                        print bad_line % line
                        continue
                    self.dbs_tree_model.openDBDoc(filepath, mode)
                    self.updateRecentFiles(filepath, mode)
            except IOError:
                print trs("""\nError: list of HDF5 files not read""",
                                'File not updated error')


    def closeEvent(self, event):
        """
        Handle close events.

        Clicking the close button of the main window titlebar causes
        the application quitting immediately, leaving things in a non
        consistent state. This event handler ensures that the needed
        tidy up is done before to quit.
        """

        # Main window close button clicked
        self.fileExit()


    def makeCopy(self):
        """Copy text/leaf depending on which widget has focus.
        """

        if self.dbs_tree_view.hasFocus():
            self.nodeCopy()
        elif self.logger.hasFocus():
            self.logger.copy()

    # Updating appearance means:
    # 
    #     * changing the toolbar buttons look when their tied QActions are
    #       enabled/disabled
    #     * updating content of menus and submenus
    # 
    # Updating state means:
    # 
    #     * toggling state of QActions i.e. enabling/disabling QActions
    # 

    def updateActions(self):
        """
        Update the state of the actions tied to menu items and toolbars.

        Every time that the selected item changes in the tree viewer the
        state of the actions must be updated because it depends on the
        type of selected item (leaf or group, opening mode etc.).
        The following events trigger a call to this slot:

            * insertion/deletion of rows in the tree of databases model
              (see VTApp.slotUpdateCurrent method)
            * changes in the selection state of the tree of databases view
              (see DBsTreeView.currentChanged method)

        The slot should be manually called when a new view is activated in
        the workspace (for instance by methods nodeOpen, nodeClose).

        .. _Warning:

        Warning! Don\'t call this method until the GUI initialisation finishes.
        It will fail if it is invoqued before the required database is open.
        This is the reason why connectSignals() is called as late as possible
        in the constructor.

        :Parameter current: the model index of the current item
        """

        # The following actions are always active:
        # fileNew, fileOpen, fileOpenRO, fileExit and the Help menu actions

        # The set of actions that can be enabled or disabled
        actions = frozenset(['fileClose', 'fileCloseAll', 'fileSaveAs', 
                            'nodeOpen', 'nodeClose', 'nodeProperties', 
                            'nodeNew', 'nodeRename', 'nodeCut', 'nodeCopy', 
                            'nodePaste', 'nodeDelete', 
                            'queryNew', 'queryDeleteAll'])
        enabled = set([])

        model_rows = self.dbs_tree_model.rowCount(QtCore.QModelIndex())
        if model_rows <= 0:
            return

        # If there are open files aside the temporary DB
        if model_rows > 1:
            enabled = enabled.union(['fileCloseAll'])

        # if there are filtered tables --> queryDeleteAll is enabled
        tmp_index = self.dbs_tree_model.index(model_rows - 1, 0, 
            QtCore.QModelIndex())
        ftables = self.dbs_tree_model.rowCount(tmp_index)
        if ftables > 0:
            enabled = enabled.union(['queryDeleteAll'])

        current = self.dbs_tree_view.currentIndex()
        node = self.dbs_tree_model.nodeFromIndex(current)
        if node != self.dbs_tree_model.root:
            # Actions always enabled for every node
            enabled = enabled.union(['nodeProperties', 
                                     'nodeCopy'])

            # If the selected file is not the temporary DB
            if node.filepath != self.dbs_tree_model.tmp_filepath:
                enabled = enabled.union(['fileSaveAs', 'fileClose'])

            kind = node.node_kind
            # If the node is a table --> queryNew is enabled
            if kind == 'table':
                enabled = enabled.union(['queryNew'])

            # If the file is not open in read-only mode
            mode = self.dbs_tree_model.getDBDoc(node.filepath).mode
            if mode != 'r':
                if kind == 'root group':
                    enabled = enabled.union(['nodeNew', 'nodePaste'])
                elif kind == 'group':
                    enabled = enabled.union(['nodeNew', 'nodeRename', 
                                            'nodeCut', 'nodePaste', 
                                            'nodeDelete'])
                elif kind == 'table':
                    enabled = enabled.union(['nodeRename', 'nodeCut', 
                                            'nodeDelete'])
                else:
                    enabled = enabled.union(['nodeRename', 'nodeCut', 
                                            'nodeDelete'])

            if kind not in ('group', 'root group'):
                if node.has_view:
                    enabled = enabled.union(['nodeClose'])
                else:
                    enabled = enabled.union(['nodeOpen'])

        disabled = actions.difference(enabled)
        for action in enabled:
            self.gui_actions[action].setEnabled(True)
        for action in disabled:
            self.gui_actions[action].setDisabled(True)


    def updateRecentFiles(self, filepath, mode):
        """
        Add a new path to the list of most recently open files.

        ``processCommandLineArgs``, ``recoverLastSession``, ``fileNew``,
        and ``fileOpen`` call this method.

        :Parameters:

            - `filepath`: the last opened/created file
            - `mode`: the opening mode of the file
        """

        item = mode + u'#@#' + filepath
        recent_files = self.config.recent_files
        # Updates the list of recently open files. Most recent goes first.
        if not recent_files.contains(item):
            recent_files.insert(0, item)
        else:
            recent_files.removeAt(recent_files.indexOf(item))
            recent_files.insert(0, item)
        while recent_files.count() > self.number_of_recent_files:
            recent_files.takeLast()


    def updateRecentSubmenu(self):
        """Update the content of the Open Recent File submenu."""

        index = 0
        self.open_recent_submenu.clear()
        iconset = vitables.utils.getIcons()
        for item in self.config.recent_files:
            index += 1
            (mode, filepath) = item.split('#@#')
            action = QtGui.QAction(u'%s. ' % index + filepath, self)
            action.setData(QtCore.QVariant(item))
            action.triggered.connect(self.openRecentFile)
            if mode == 'r':
                action.setIcon(iconset['file_ro'])
            else:
                action.setIcon(iconset['file_rw'])
            self.open_recent_submenu.addAction(action)

        # Always add a separator and a clear QAction. So if the menu is empty
        # the user still will know what's going on
        self.open_recent_submenu.addSeparator()
        action = QtGui.QAction(trs('&Clear',
            'A recent submenu command'), self)
        action.triggered.connect(self.clearRecentFiles)
        self.open_recent_submenu.addAction(action)


    def updateWindowsMenu(self):
        """
        Update the Windows menu.

        The Windows menu is dynamic because its content is determined
        by the currently open views. Because the number of these views or
        its contents may vary at any moment we must update the Windows
        menu every time it is open. For simplicity we don't keep track
        of changes in the menu content. Instead, we clean and create it
        from scratch every time it is about to show.
        """

        self.windows_menu.clear()
        windows_actions = ['windowCascade', 'windowTile', 
                           'windowRestoreAll', 'windowMinimizeAll', 
                           'windowClose', 'windowCloseAll', None]
        vitables.utils.addActions(self.windows_menu, windows_actions, 
                                    self.gui_actions)
        windows_list = self.workspace.subWindowList()
        if not windows_list:
            return
        self.windows_menu.setSeparatorsCollapsible(True)

        menu = self.windows_menu
        counter = 1
        for window in windows_list:
            title = window.windowTitle()
            if counter == 10:
                menu.addSeparator()
                menu = menu.addMenu(trs("&More", 'A Windows submenu'))
            accel = ""
            if counter < 10:
                accel = "&%d " % counter
            elif counter < 36:
                accel = "&%c " % chr(counter + ord("@") - 9)
            action = menu.addAction("%s%s" % (accel, title))
            action.setCheckable(True)
            if self.workspace.activeSubWindow() == window:
                action.setChecked(True)
            menu.action_group.addAction(action)
            action.triggered.connect(self.window_mapper.map)
            self.window_mapper.setMapping(action, window)
            counter = counter + 1


    def updateStatusBar(self):
        """Update the permanent message of the status bar.
        """

        current = self.dbs_tree_view.currentIndex()
        if current.isValid():
            tip = self.dbs_tree_model.data(current, QtCore.Qt.StatusTipRole)
            message = tip.toString()
        else:
            message = ''
        self.sb_node_info.setText(message)


    def popupContextualMenu(self, kind, pos):
        """
        Popup a contextual menu in the tree of databases view.

        When a point of the tree view is right clicked, a contextual
        popup is displayed. The content of the popup depends on the
        kind of node pointed: no node, root group, group or leaf.

        :Parameters:

            - `kind`: defines the content of the menu
            - `pos`: the clicked point in global coordinates
        """

        if kind == 'view':
            menu = self.view_cm
        elif kind == 'root group':
            menu = self.root_node_cm
        elif kind == 'group':
            menu = self.group_node_cm
        else:
            menu = self.leaf_node_cm
        menu.popup(pos)


    def closeChildrenViews(self, nodepath, filepath):
        """Close views being overwritten during node editing.

        :Parameters:

            - `nodepath`: the full path of the node that is overwrting other nodes
            - `filepath`: the full path of the file where that node lives
        """

        for window in self.workspace.subWindowList():
            wnodepath = window.dbt_leaf.nodepath
            wfilepath = window.dbt_leaf.filepath
            if not wfilepath == filepath:
                continue
            if wnodepath[0:len(nodepath)] == nodepath:
                window.close()


    def changeMDIViewMode(self):
        """Toggle the view mode of the workspace.
        """

        if self.workspace.viewMode() == QtGui.QMdiArea.SubWindowView:
            self.workspace.setViewMode(QtGui.QMdiArea.TabbedView)
        else:
            self.workspace.setViewMode(QtGui.QMdiArea.SubWindowView)


    def eventFilter(self, widget, event):
        """Event filter used to provide the MDI area with a context menu.

        :Parameters:
            -`widget`: the widget that receives the event
            -`event`: the event being processed
        """

        if widget == self.workspace:
            if event.type() == QtCore.QEvent.ContextMenu:
                pos = event.globalPos()
                self.mdi_cm.popup(pos)
            return QtGui.QMdiArea.eventFilter(widget, widget, event)
        else:
            return QtGui.QMainWindow.eventFilter(self, widget, event)


    def updateFSHistory(self, working_dir):
        """Update the navigation history of the file selector widget.

        :Parameter `working_dir`: the last visited directory
        """

        self.config.last_working_directory = working_dir
        if not self.file_selector_history.contains(working_dir):
            self.file_selector_history.append(working_dir)
        else:
            self.file_selector_history.removeAll(working_dir)
            self.file_selector_history.append(working_dir)


    def checkFileExtension(self, filepath):
        """
        Check the filename extension of a given file.

        If the filename has no extension this method adds .h5
        extension to it. This is useful when a file is being created or
        saved.

        :Parameter filepath: the full path of the file (a QString)

        :Returns: the filepath with the proper extension (a Python string)
        """

        if not re.search('\.(.+)$', os.path.basename(filepath)):
            ext = '.h5'
            filepath = filepath + ext
        return filepath


    def fileNew(self):
        """Create a new file."""

        # Launch the file selector
        fs_args = {'accept_mode': QtGui.QFileDialog.AcceptOpen, 
            'file_mode': QtGui.QFileDialog.AnyFile, 
            'history': self.file_selector_history, 
            'label': trs('Create', 'Accept button text for QFileDialog')}
        filepath, working_dir = vitables.utils.getFilepath(
            self, 
            trs('Creating a new file...', 
                'Caption of the File New... dialog'), 
            dfilter=trs("""HDF5 Files (*.h5 *.hd5 *.hdf5);;"""
                """All Files (*)""", 'Filter for the Open New dialog'), 
            settings=fs_args)

        if not filepath:
            # The user has canceled the dialog
            return

        # Update the history of the file selector widget
        self.updateFSHistory(working_dir)

        # Check the file extension
        filepath = self.checkFileExtension(filepath)

        # Check the returned path
        if os.path.exists(filepath):
            print trs(
                """\nWarning: """
                """new file creation failed because file already exists.""",
                'A file creation error')
            return

        # Create the pytables file and close it.
        db_doc = self.dbs_tree_model.createDBDoc(filepath)
        if db_doc:
            # The write mode must be replaced by append mode or the file
            # will be created from scratch in the next ViTables session
            self.updateRecentFiles(filepath, 'a')


    def fileSaveAs(self):
        """
        Save a renamed copy of a file.

        This method exhibits the typical behavior: copied file is closed
        and the fresh renamed copy is opened.
        """

        overwrite = False
        current_index = self.dbs_tree_view.currentIndex()

        # The file being saved
        initial_filepath = \
            self.dbs_tree_model.nodeFromIndex(current_index).filepath

        # Launch the file selector
        fs_args = {'accept_mode': QtGui.QFileDialog.AcceptSave, 
            'file_mode': QtGui.QFileDialog.AnyFile, 
            'history': self.file_selector_history, 
            'label': trs('Create', 'Accept button text for QFileDialog')}
        trier_filepath, working_dir = vitables.utils.getFilepath(
            self, 
            trs('Copying a file...', 
                      'Caption of the File Save as... dialog'), 
            dfilter = trs("""HDF5 Files (*.h5 *.hd5 *.hdf5);;"""
                """All Files (*)""", 'Filter for the Save As... dialog'), 
            filepath=initial_filepath, 
            settings=fs_args)

        if not trier_filepath:  # The user has canceled the dialog
            return

        # Update the history of the file selector widget
        self.updateFSHistory(working_dir)

        trier_filepath = self.checkFileExtension(trier_filepath)

        #
        # Check if the chosen name is valid
        #

        info = [trs('File Save as: file already exists', 
                'A dialog caption'), None]
        # Bad filepath conditions
        trier_dirname, trier_filename = os.path.split(trier_filepath)
        sibling = os.listdir(trier_dirname)
        filename_in_sibling = trier_filename in sibling
        is_tmp_filepath = trier_filepath == self.dbs_tree_model.tmp_filepath
        is_initial_filepath = trier_filepath == initial_filepath

        # If the suggested filepath is not valid ask for a new filepath
        # The loop is necessary because the file being saved as and the
        # temporary database can be in the same directory. In this case
        # we must check all error conditions every time a new name is tried
        while is_tmp_filepath or is_initial_filepath or filename_in_sibling:
            if is_tmp_filepath:
                info[1] = trs("""Target directory: %s\n\nThe Query """
                                """results database cannot be overwritten.""", 
                                'Overwrite file dialog label') % trier_dirname
                pattern = \
                    "(^%s$)|[a-zA-Z_]+[0-9a-zA-Z_]*(?:\.[0-9a-zA-Z_]+)?$" \
                    % trier_filename
            elif is_initial_filepath:
                info[1] = trs("""Target directory: %s\n\nThe file """
                                """being saved cannot overwrite itself.""", 
                                'Overwrite file dialog label') % trier_dirname
                pattern = \
                    "(^%s$)|[a-zA-Z_]+[0-9a-zA-Z_]*(?:\.[0-9a-zA-Z_]+)?$" \
                    % trier_filename
            elif filename_in_sibling:
                info[1] = trs("""Target directory: %s\n\nFile name """
                    """'%s' already in use in that directory.\n""", 
                    'Overwrite file dialog label') % (trier_dirname, 
                    trier_filename)
                pattern = "[a-zA-Z_]+[0-9a-zA-Z_]*(?:\.[0-9a-zA-Z_]+)?$"

            dialog = renameDlg.RenameDlg(trier_filename, pattern, info)
            if dialog.exec_():
                trier_filename = dialog.action['new_name']
                trier_filepath = os.path.join(trier_dirname, trier_filename)
                trier_filepath = \
                    unicode(QtCore.QDir.fromNativeSeparators(trier_filepath))
                overwrite = dialog.action['overwrite']
                # Update the error conditions
                is_initial_filepath = trier_filepath == initial_filepath
                is_tmp_filepath = \
                    trier_filepath == self.dbs_tree_model.tmp_filepath
                filename_in_sibling = trier_filename in sibling
                del dialog
                if (overwrite == True) and (not is_initial_filepath) and \
                    (not is_tmp_filepath):
                    break
            else:
                del dialog
                return

        filepath = self.checkFileExtension(trier_filepath)

        # If an open file is overwritten then close it
        if overwrite and self.dbs_tree_model.getDBDoc(filepath):
            for row, child in enumerate(self.dbs_tree_model.root.children):
                if child.filepath == filepath:
                    self.fileClose(self.dbs_tree_model.index(row, 0, 
                                                        QtCore.QModelIndex()))
            # The current index could have changed when overwriting
            # so we update it
            for row in range(0, 
                self.dbs_tree_model.rowCount(QtCore.QModelIndex())):
                index = QtCore.QModelIndex().child(row, 0)
                node = self.dbs_tree_model.nodeFromIndex(index)
                if node.filepath == initial_filepath:
                    current_index = index
            self.dbs_tree_view.setCurrentIndex(current_index)

        # Make a copy of the selected file
        try:
            QtGui.qApp.setOverrideCursor(QtGui.QCursor(QtCore.Qt.WaitCursor))
            dbdoc = self.dbs_tree_model.getDBDoc(initial_filepath)
            dbdoc.copyFile(filepath)
        finally:
            QtGui.qApp.restoreOverrideCursor()

        # Close the copied file (which is not necessarely selected in
        # the tree view because closing an overwritten file can change
        # the selected item) and open the new copy in read-write mode.
        # The position in the tree is kept
        for row, child in enumerate(self.dbs_tree_model.root.children):
            if child.filepath == initial_filepath:
                self.fileClose(self.dbs_tree_model.index(row, 0, 
                                                        QtCore.QModelIndex()))
                self.fileOpen(filepath, 'a', row) 


    def fileOpenRO(self, filepath=None):
        """
        Open a file that contains a ``PyTables`` database in read-only mode.

        :Parameters filepath: the full path of the file to be open
        """
        self.fileOpen(filepath, mode='r')


    def openRecentFile(self):
        """
        Opens the file whose path appears in the activated menu item text.
        """

        action = self.sender()
        item = action.data().toString()
        (mode, filepath) = unicode(item).split('#@#')
        self.fileOpen(filepath, mode)


    def clearRecentFiles(self):
        """
        Clear the list of recently opened files and delete the corresponding
        historical file.
        """

        self.config.recent_files.clear()


    def fileOpen(self, filepath=None, mode='a', position=0):
        """
        Open a file that contains a ``PyTables`` database.

        If this method is invoqued via ``File -> Open`` then no filepath
        is passed and a dialog is raised. When the method is invoqued
        via slotRecentSubmenuActivated or fileSaveAs methods then
        filepath is passed and the dialog is not raised.

        :Parameters:

        - `filepath`: the full path of the file to be open
        - `mode`: the file opening mode. It can be read-write or read-only
        - `position`: position in the tree view of the new file
        """

        if not filepath:
            # Launch the file selector
            fs_args = {'accept_mode': QtGui.QFileDialog.AcceptOpen, 
                'file_mode': QtGui.QFileDialog.ExistingFile, 
                'history': self.file_selector_history, 
                'label': trs('Open', 'Accept text for QFileDialog')}
            filepath, working_dir = vitables.utils.getFilepath(\
                self, 
                trs('Select a file for opening', 
                'Caption of the File Open... dialog'), 
                dfilter = trs("""HDF5 Files (*.h5 *.hd5 *.hdf5);;"""
                    """All Files (*)""", 'Filter for the Open New dialog'), 
                settings=fs_args)

            if not filepath:
                # The user has canceled the dialog
                return

            # Update the history of the file selector widget
            self.updateFSHistory(working_dir)

        else:
            # Make sure the path contains no backslashes
            filepath = unicode(QtCore.QDir.fromNativeSeparators(filepath))

        # Open the database and select it in the tree view
        self.dbs_tree_model.openDBDoc(filepath, mode, position)
        database = self.dbs_tree_model.getDBDoc(filepath)
        if database:
            self.dbs_tree_view.setCurrentIndex(\
                self.dbs_tree_model.index(position, 0, QtCore.QModelIndex()))
            self.updateRecentFiles(filepath, mode)


    def fileClose(self, current=False):
        """
        Close a file.

        First of all this method finds out which database it has to close.
        Afterwards all views belonging to that database are closed, then
        the object tree is removed from the QListView and, finally, the
        database is closed.

        current: the index of a node living in the file being closed
        """

        if current is False:
            current = self.dbs_tree_view.currentIndex()
        filepath = self.dbs_tree_model.nodeFromIndex(current).filepath

        # If some leaf of this database has an open view then close it
        for window in self.workspace.subWindowList():
            if window.dbt_leaf.filepath == filepath:
                window.close()

        # The tree model closes the file and delete its root item
        # from the tree view
        dbdoc = self.dbs_tree_model.getDBDoc(filepath)
        if dbdoc.hidden_group is not None:
            dbdoc.h5file.removeNode(dbdoc.hidden_group, recursive=True)
        self.dbs_tree_model.closeDBDoc(filepath)


    def fileCloseAll(self):
        """Close every file opened by user."""

        # The list of top level items to be removed.
        # The temporary database should be closed at quit time only
        open_files = len(self.dbs_tree_model.root.children) - 1
        rows_range = range(0, open_files)
        # Reversing is a must because, if we start from 0, row positions
        # change as we delete rows
        rows_range.reverse()
        for row in rows_range:
            index = self.dbs_tree_model.index(row, 0, QtCore.QModelIndex())
            self.fileClose(index)


    def fileExit(self):
        """
        Safely closes the application.

        Save current configuration on disk, closes opened files and exits.
        """

        # Close all browsers
        if self.doc_browser:
            self.doc_browser.slotExitBrowser()
        # Save current configuration
        self.config.saveConfiguration()
        # Close every user opened file
        self.fileCloseAll()
        # Close the temporary database
        index = self.dbs_tree_model.index(0, 0, QtCore.QModelIndex())
        self.fileClose(index)
        # Application quit
        QtGui.qApp.quit()


    def nodeOpen(self, current=False):
        """
        Opens a leaf node for viewing.

        :Parameter current: the model index of the item to be opened
        """

        if current is False:
            # Open the node currently selected in the tree of databases
            index = self.dbs_tree_view.currentIndex()
        else:
            # When restoring the previous session explicit indexes are passed
            index = current
        dbs_tree_leaf = self.dbs_tree_model.nodeFromIndex(index)
        leaf = dbs_tree_leaf.node # A PyTables node

        # tables.UnImplemented datasets cannot be read so are not opened
        if isinstance(leaf, tables.UnImplemented):
            QtGui.QMessageBox.information(self, 
                trs('About UnImplemented nodes', 'A dialog caption'), 
                trs(
                """Actual data for this node are not accesible.<br> """
                """The combination of datatypes and/or dataspaces in this """
                """node is not yet supported by PyTables.<br>"""
                """If you want to see this kind of dataset implemented in """
                """PyTables, please, contact the developers.""",
                'Text of the Unimplemented node dialog'))
            return

        # The buffer tied to this node in order to optimize the read access
        leaf_buffer = rbuffer.Buffer(leaf)

        # Leaves that cannot be read are not opened
        if not leaf_buffer.isDataSourceReadable():
            return

        # Create a view and announce it.
        # Announcing is potentially helpful for plugins in charge of
        # datasets customisations (for instance, additional formatting)
        subwindow = dataSheet.DataSheet(index)
        subwindow.show()
        self.leaf_model_created.emit(subwindow)


    def nodeClose(self, current=False):
        """
        Closes the view of the selected node.

        The method is called by activating ``Node --> Close`` (what passes
        no argument) or programatically by the ``VTApp.fileClose()``
        method (what does pass argument).
        If the target is an open leaf this method closes its view, delete
        its model and updates the controller tracking system.
        If the target node is a root group the method looks for opened
        children and closes them as described above.

        :Parameter current: the tree view item to be closed
        """

        current = self.dbs_tree_view.currentIndex()
        pcurrent = QtCore.QPersistentModelIndex(current)
        # Find out the subwindow tied to the selected node and close it
        for data_sheet in self.workspace.subWindowList():
            if pcurrent == data_sheet.pindex:
                data_sheet.close()
                break


    def nodeNewGroup(self):
        """Create a new group node."""

        current = self.dbs_tree_view.currentIndex()
        parent = self.dbs_tree_model.nodeFromIndex(current)

        # Get the new group name
        dialog = inputNodeName.InputNodeName(\
            trs('Creating a new group', 'A dialog caption'), 
            trs('Source file: %s\nParent group: %s\n\n ', 
                'A dialog label') % (parent.filepath, parent.nodepath), 
            trs('Create', 'A button label'))
        if dialog.exec_():
            suggested_nodename = dialog.node_name
            del dialog
        else:
            del dialog
            return

        #
        # Check if the entered nodename is already in use
        #
        sibling = getattr(parent.node, '_v_children').keys()
        pattern = "[a-zA-Z_]+[0-9a-zA-Z_ ]*"
        info = [trs('Creating a new group: name already in use', 
                'A dialog caption'), 
                trs("""Source file: %s\nParent group: %s\n\nThere is """
                          """already a node named '%s' in that parent group"""
                          """.\n""", 'A dialog label') % \
                    (parent.filepath, parent.nodepath, suggested_nodename)]
        nodename, overwrite = vitables.utils.getFinalName(suggested_nodename, 
            sibling, pattern, info)
        if nodename is None:
            return

        # If the creation overwrites a group with attached views then these
        # views are closed before the renaming is done
        if overwrite:
            nodepath = tables.path.joinPath(parent.nodepath, nodename)
            self.closeChildrenViews(nodepath, parent.filepath)

        self.dbs_tree_model.createGroup(current, nodename, overwrite)


    def nodeRename(self):
        """
        Rename the selected node.

        - ask for the node name
        - check the node name. If it is already in use ask what to<br>
          do (possibilities are rename, overwrite and cancel creation)
        - rename the node
        """

        index = self.dbs_tree_view.currentIndex()
        child = self.dbs_tree_model.nodeFromIndex(index)
        parent = child.parent

        # Get the new nodename
        dialog = inputNodeName.InputNodeName(\
            trs('Renaming a node', 'A dialog caption'),
            trs('Source file: %s\nParent group: %s\n\n', 
                    'A dialog label') % (parent.filepath, parent.nodepath), 
            trs('Rename', 'A button label'))
        if dialog.exec_():
            suggested_nodename = dialog.node_name
            del dialog
        else:
            del dialog
            return

        #
        # Check if the nodename is already in use
        #
        sibling = getattr(parent.node, '_v_children').keys()
        # Note that current nodename is not allowed as new nodename.
        # Embedding it in the pattern makes unnecessary to pass it to the
        # rename dialog via method argument and simplifies the code
        pattern = """(^%s$)|""" \
            """(^[a-zA-Z_]+[0-9a-zA-Z_ ]*)""" % child.name
        info = [trs('Renaming a node: name already in use', 
                'A dialog caption'), 
                trs("""Source file: %s\nParent group: %s\n\nThere is """
                          """already a node named '%s' in that parent """
                          """group.\n""", 'A dialog label') % \
                    (parent.filepath, parent.nodepath, suggested_nodename)]
        nodename, overwrite = vitables.utils.getFinalName(suggested_nodename, 
            sibling, pattern, info)
        if nodename is None:
            return

        # If the renaming overwrites a node with attached views then these
        # views are closed before the renaming is done
        if overwrite:
            nodepath = tables.path.joinPath(parent.nodepath, nodename)
            self.closeChildrenViews(nodepath, child.filepath)

        # Rename the node
        self.dbs_tree_model.renameNode(index, nodename, overwrite)

        # Update the Selected node indicator of the status bar
        self.updateStatusBar()


    def nodeCut(self):
        """Cut the selected node."""

        current = self.dbs_tree_view.currentIndex()

        # If the cut node has attached views then these views are closed
        # before the cutting is done. This behavior can be inconvenient
        # for users but get rid of potential problems that arise if, for
        # any reason, the user doesn't paste the cut node.
        node = self.dbs_tree_model.nodeFromIndex(current)
        self.closeChildrenViews(node.nodepath, node.filepath)

        # Cut the node
        self.dbs_tree_model.cutNode(current)


    def nodeCopy(self):
        """
        Copy the selected node.
        """

        current = self.dbs_tree_view.currentIndex()

        # Non readable leaves should not be copied
        dbs_tree_node = self.dbs_tree_model.nodeFromIndex(current)
        if not (dbs_tree_node.node_kind in ('root group', 'group')):
            leaf = dbs_tree_node.node # A PyTables node
            leaf_buffer = rbuffer.Buffer(leaf)
            if not leaf_buffer.isDataSourceReadable():
                QtGui.QMessageBox.information(self, 
                    trs('About unreadable datasets', 'Dialog caption'), 
                    trs(
                    """Sorry, actual data for this node are not accesible."""
                    """<br>The node will not be copied.""", 
                    'Text of the Unimplemented node dialog'))
                return

        # Copy the node
        self.dbs_tree_model.copyNode(current)


    def nodePaste(self):
        """
        Paste the currently copied/cut node under the selected node.
        """

        current = self.dbs_tree_view.currentIndex()
        parent = self.dbs_tree_model.nodeFromIndex(current)

        copied_node_info = self.dbs_tree_model.copied_node_info
        if copied_node_info == {}:
            return

        src_node = copied_node_info['node']
        src_filepath = src_node.filepath
        src_nodepath = src_node.nodepath
        if src_nodepath == '/':
            nodename = 'root_group_of_%s' \
                        % os.path.basename(src_filepath)
        else:
            nodename = src_node.name

        dbdoc = \
            self.dbs_tree_model.getDBDoc(copied_node_info['initial_filepath'])
        if not dbdoc:
            # The database where the copied/cut node lived has been closed
            return
        if src_filepath != copied_node_info['initial_filepath']:
            # The copied/cut node doesn't exist. It has been moved to
            # other file
            return

        # Check if the copied node still exists in the tree of databases
        if copied_node_info['is_copied']:
            if src_nodepath != copied_node_info['initial_nodepath']:
                # The copied node doesn't exist. It has been moved somewhere
                return
            if not dbdoc.h5file.__contains__(src_nodepath):
                return

            # Check if pasting is allowed. It is not when the node has been
            # copied (pasting cut nodes has no restrictions) and
            # - source and target are the same node
            # - target is the source's parent
            if (src_filepath == parent.filepath):
                if (src_nodepath == parent.nodepath) or \
                   (parent.nodepath == src_node.parent.nodepath):
                    return

        #
        # Check if the nodename is already in use
        #
        sibling = getattr(parent.node, '_v_children').keys()
        # Nodename pattern
        pattern = "[a-zA-Z_]+[0-9a-zA-Z_ ]*"
        # Bad nodename conditions
        info = [trs('Node paste: nodename already exists', 
                'A dialog caption'), 
                trs("""Source file: %s\nCopied node: %s\n"""
                    """Destination file: %s\nParent group: %s\n\n"""
                    """Node name '%s' already in use in that group.\n""", 
                    'A dialog label') % \
                    (src_filepath, src_nodepath,
                    parent.filepath, parent.nodepath, nodename), 
                trs('Paste', 'A button label')]
        # Validate the nodename
        nodename, overwrite = vitables.utils.getFinalName(nodename, sibling, 
            pattern, info)
        if nodename is None:
            return

        # If the pasting overwrites a node with attached views then these
        # views are closed before the pasting is done
        if overwrite:
            nodepath = tables.path.joinPath(parent.nodepath, nodename)
            self.closeChildrenViews(nodepath, parent.filepath)

        # Paste the node
        self.dbs_tree_model.pasteNode(current, nodename, overwrite)


    def nodeDelete(self, current=False, force=None):
        """
        Delete a given node.

        :Parameters;

            - `force`: ask/do not ask for confirmation before deletion
        """

        if current is False:
            current = self.dbs_tree_view.currentIndex()
        node = self.dbs_tree_model.nodeFromIndex(current)

        # Confirm deletion dialog
        if not force:
            title = trs('Node deletion', 'Caption of the node deletion dialog')
            text = trs("""\nYou are about to delete the node:\n%s\n""", 
                'Ask for confirmation') % node.nodepath
            itext = ''
            dtext = ''
            buttons = {\
                'Delete': \
                    (trs('Delete', 'Button text'), QtGui.QMessageBox.YesRole), 
                'Cancel': \
                    (trs('Cancel', 'Button text'), QtGui.QMessageBox.NoRole), 
                }

            # Ask for confirmation
            answer = \
                vitables.utils.questionBox(title, text, itext, dtext, buttons)
            if answer == 'Cancel':
                return

        # If item is a filtered table then update the list of used names
        if hasattr(node.node._v_attrs, 'query_condition'):
            self.queries_mgr.ft_names.remove(node.name)

        # If the deletion involves a node with attached views then these
        # views are closed before the deletion is done
        self.closeChildrenViews(node.nodepath, node.filepath)

        # Delete the node
        self.dbs_tree_model.deleteNode(current)

        # Synchronise the workspace with the tree of databases pane i.e.
        # ensure that the new current node (if any) gets selected
        select_model = self.dbs_tree_view.selectionModel()
        new_current = self.dbs_tree_view.currentIndex()
        select_model.select(new_current, QtGui.QItemSelectionModel.Select)


    def nodeProperties(self):
        """
        Display the properties dialog for the currently selected node.

        The method is called by activating Node --> Properties.
        """

        current = self.dbs_tree_view.currentIndex()
        node = self.dbs_tree_model.nodeFromIndex(current)
        info = nodeInfo.NodeInfo(node)
        nodePropDlg.NodePropDlg(info)


    def settingsPreferences(self):
        """
        Launch the Preferences dialog.

        Clicking the ``OK`` button applies the configuration set in the
        Preferences dialog.
        """

        prefs =  preferences.Preferences()
        try:
            if prefs.exec_() == QtGui.QDialog.Accepted:
                self.config.loadConfiguration(prefs.new_prefs)
        finally:
            del prefs


    def windowsClose(self):
        """Close the window currently active in the workspace."""
        self.workspace.activeSubWindow().close()


    def windowsCloseAll(self):
        """Close all open windows."""

        for window in self.workspace.subWindowList():
            window.close()


    def windowsRestoreAll(self):
        """Restore every window in the workspace to its normal size."""

        for window in self.workspace.subWindowList():
            window.showNormal()


    def windowsMinimizeAll(self):
        """Restore every window in the workspace to its normal size."""

        for window in self.workspace.subWindowList():
            window.showMinimized()


    def helpBrowser(self):
        """
        Open the documentation browser

        Help --> UsersGuide
        """

        self.doc_browser = helpBrowser.HelpBrowser()


    def helpAbout(self):
        """
        Show a tabbed dialog with the application About and License info.

        Help --> About
        """

        # Text to be displayed
        about_text = trs(
            """<qt>
            <h3>ViTables %s</h3>
            ViTables is a graphical tool for displaying datasets
            stored in PyTables and HDF5 files. It is written using PyQt
            , the Python bindings for the Qt GUI toolkit.<p>
            For more information see
            <b>http://www.vitables.org</b>.<p>
            Please send bug reports or feature requests to the
            <em>ViTables Users Group</em>.<p>
            ViTables uses third party software which is copyrighted by
            its respective copyright holder. For details see the
            copyright notice of the individual packages.
            </qt>""",
            'Text of the About ViTables dialog')  % vtconfig.getVersion()
        thanks_text = trs(
            """<qt>
            Dmitrijs Ledkovs for contributing the new and greatly enhanced
            build system and for making Debian packages.<p>
            Oxygen team for a wonderful icons set.<p>
            All the people who reported bugs and made suggestions.
            </qt>""",
            'Text of the About ViTables dialog (Thanks to page)')
        license_text = vitables.utils.getLicense()

        # Construct the dialog
        about_dlg = QtGui.QDialog(self)
        about_dlg.setWindowTitle(trs('About ViTables %s',
            'Caption of the About ViTables dialog') % vtconfig.getVersion())
        layout = QtGui.QVBoxLayout(about_dlg)
        tab_widget = QtGui.QTabWidget(about_dlg)
        buttons_box = QtGui.QDialogButtonBox(QtGui.QDialogButtonBox.Ok)
        layout.addWidget(tab_widget)
        layout.addWidget(buttons_box)

        buttons_box.accepted.connect(about_dlg.accept)

        # Make About page
        content = [about_text, thanks_text, license_text]
        tabs = [trs('&About',
            'Title of the first tab of the About dialog'), 
            trs('&Thanks To',
            'Title of the second tab of the About dialog'), 
            trs('&License',
            'Title of the third tab of the About dialog')]

        for index in range(0, 3):
            widget = self.makePage(content[index])
            tab_widget.addTab(widget, tabs[index])


        # Show the dialog
        about_dlg.exec_()


    def makePage(self, content):
        """Create a page for the About ViTables dialog.

        :Parameter content: the text displayed on the page
        """

        widget = QtGui.QWidget()
        widget.setLayout(QtGui.QVBoxLayout())
        text_edit = QtGui.QTextEdit(widget)
        text_edit.setReadOnly(1)
        text_edit.setAcceptRichText(True)
        text_edit.setText(content)
        widget.layout().addWidget(text_edit)

        return widget


    def helpAboutQt(self):
        """
        Shows a message box with the Qt About info.

        Help --> About Qt
        """

        QtGui.QMessageBox.aboutQt(self, trs('About Qt',
            'Caption of the About Qt dialog'))


    def helpVersions(self):
        """
        Message box with info about versions of libraries used by
        ViTables.

        Help --> Show Versions
        """

        # The libraries versions dictionary
        libs_versions = {
            'title': trs('Version Numbers',
                'Caption of the Versions dialog'),
            'Python': reduce(lambda x,y: '.'.join([unicode(x), unicode(y)]), 
                sys.version_info[:3]),
            'PyTables': tables.__version__ ,
            'NumPy': tables.numpy.__version__,
            'Qt': QtCore.qVersion(),
            'PyQt': QtCore.PYQT_VERSION_STR,
            'ViTables': vtconfig.getVersion()
        }

        # Add new items to the dictionary
        libraries = ('HDF5', 'Zlib', 'LZO', 'BZIP2')
        for lib in libraries:
            lversion = tables.whichLibVersion(lib.lower())
            if lversion:
                libs_versions[lib] = lversion[1]
            else:
                libs_versions[lib] = trs('not available',
                    'Part of the library not found text')

        # Construct the dialog
        versions_dlg = QtGui.QDialog(self)
        versions_dlg.setWindowTitle(trs('Version Numbers', 
                                             'Caption of the Versions dialog'))
        layout = QtGui.QVBoxLayout(versions_dlg)
        versions_edit = QtGui.QTextEdit(versions_dlg)
        buttons_box = QtGui.QDialogButtonBox(QtGui.QDialogButtonBox.Ok)
        layout.addWidget(versions_edit)
        layout.addWidget(buttons_box)

        buttons_box.accepted.connect(versions_dlg.accept)

        versions_edit.setReadOnly(1)
        versions_edit.setText(\
            """
            <qt>
            <h3>%(title)s</h3><br>
            <table>
            <tr><td><b>Python</b></td><td>%(Python)s</td></tr>
            <tr><td><b>PyTables</b></td><td>%(PyTables)s</td></tr>
            <tr><td><b>NumPy</b></td><td>%(NumPy)s</td></tr>
            <tr><td><b>HDF5</b></td><td>%(HDF5)s</td></tr>
            <tr><td><b>Zlib</b></td><td>%(Zlib)s</td></tr>
            <tr><td><b>LZO</b></td><td>%(LZO)s</td></tr>
            <tr><td><b>BZIP2</b></td><td>%(BZIP2)s</td></tr>
            <tr><td><b>Qt</b></td><td>%(Qt)s</td></tr>
            <tr><td><b>PyQt</b></td><td>%(PyQt)s</td></tr>
            <tr><td><b>ViTables</b></td><td>%(ViTables)s</td></tr>
            </table>
            </qt>""" % libs_versions)

        # Show the dialog
        versions_dlg.exec_()
