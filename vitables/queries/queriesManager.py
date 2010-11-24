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

"""
Here is defined the QueriesManager class.

Classes:

* QueriesManager

Methods:


Functions:


Misc variables:

* __docformat__

"""

__docformat__ = 'restructuredtext'
_context = 'QueriesManager'

from PyQt4 import QtCore, QtGui

import vitables.utils
import vitables.queries.queryDlg as queryDlg
import vitables.queries.query as query


def trs(source, comment=None):
    """Translate string function."""
    return unicode(QtGui.qApp.translate(_context, source, comment))


def getTableInfo(table):
    """Retrieves table info required for querying it.

    :Parameter table: the tables.Table instance being queried.
    """
    info = {}
    info[u'nrows'] = table.nrows
    info[u'src_filepath'] = unicode(table._v_file.filename)
    info[u'src_path'] = table._v_pathname
    info[u'name'] = table._v_name
    # Fields info: top level fields names, flat fields shapes and types
    info[u'col_names'] = frozenset(table.colnames)
    info[u'col_shapes'] = \
        dict((k, v.shape) for (k, v) in table.coldescrs.iteritems())
    info[u'col_types'] = table.coltypes
    # Fields that can be queried
    info[u'condvars'] = {}
    info[u'valid_fields'] = []

    if info[u'nrows'] <= 0:
        print trs("""Caveat: table %s is empty. Nothing to query.""",
            'Warning message for users') % info[u'name']
        return None

    # Find out the valid (i.e. searchable) fields and condition variables.
    # First discard nested fields.
    # Beware that order matters in binary operations that mix set instances
    # with frozensets: set & frozenset returns a set but frozenset & set
    # returns a frozenset
    valid_fields = \
    set(info[u'col_shapes'].keys()).intersection(info[u'col_names'])
#    info[u'col_names'].intersection(info[u'col_shapes'].keys())

    # Then discard fields that aren't scalar and those that are complex
    for name in valid_fields.copy():
        if (info[u'col_shapes'][name] != ()) or \
        info[u'col_types'][name].count(u'complex'):
            valid_fields.remove(name)

    # Among the remaining fields, those whose names contain blanks
    # cannot be used in conditions unless they are mapped to
    # variables with valid names
    index = 0
    for name in valid_fields.copy():
        if name.count(' '):
            while (u'col%s' % index) in valid_fields:
                index = index + 1
            info[u'condvars'][u'col%s' % index] = \
                table.cols._f_col(name)
            valid_fields.remove(name)
            valid_fields.add(u'col%s (%s)' % (index, name))
            index = index + 1
    info[u'valid_fields'] = valid_fields

    # If table has not columns suitable to be filtered does nothing
    if not info[u'valid_fields']:
        print trs("""\nError: table %s has no """
        """columns suitable to be queried. All columns are nested, """
        """multidimensional or have a Complex data type.""",
        'An error when trying to query a table') % info['name']
        return None
    elif len(info[u'valid_fields']) != len(info[u'col_names']):
    # Log a message if non selectable fields exist
        print trs("""\nWarning: some table columns contain """
           """nested, multidimensional or Complex data. They """
           """cannot be queried so are not included in the Column"""
           """ selector of the query dialog.""",
           'An informational note for users')

    return info


class QueriesManager(QtCore.QObject):
    """This is the class in charge of threading the execution of queries.

    PyTables doesn't support threaded queries. So when several queries are
    requested to ViTables they will be executed sequentially. However the
    queries will not be executed in the ViTables main thread but in a
    secondary one. This way we ensure that queries (that are potentially
    long-running operations) will not freeze the user interface and ViTables
    will remain usable while queries are running (unless the queried table is
    so large or the query so complex that the query it eats all the available
    computer resources, CPU and memory).

    Also no more than one query can be made at the same time on a given table.
    This goal is achieved in a very simple way: tracking the tables currently
    being queried in a data structure (a dictionary at present).
    """

    def __init__(self, parent=None):
        """Setup the queries manager.

        The manager is in charge of:

        - keep a description of the last query made
        - automatically generate names for new queries
        - track the query names already in use
        - track the tables that are currently being queried

        The last query description has three components: the filepath of
        the file where the queried table lives, the nodepath of the queried
        table and the query condition.

        A query name is the name of the table where the query results are
        stored. By default it has the format "Filtered_TableUID" where UID
        is an integer automatically generated. User can customise the query
        name in the New Query dialog.
        """

        super(QueriesManager, self).__init__(parent)

        # Description of the last query made
        self.last_query = [None, None, None]
        # UID for automatically generating query names
        self.counter = 0
        # The list of query names currently in use
        self.ft_names = []

        self.vtapp = vitables.utils.getVTApp()
        self.vtgui = self.vtapp.gui
        self.dbt_view = self.vtgui.dbs_tree_view
        self.dbt_model = self.vtgui.dbs_tree_model


    def newQuery(self):
        """Process the query requests launched by users.
        """

        # The VTApp.updateQueryActions method ensures that the current node is
        # tied to a tables.Table instance so we can query it without
        # further checking
        current = self.dbt_view.currentIndex()
        node = self.dbt_model.nodeFromIndex(current)
        table_uid = node.as_record
        table = node.node

        table_info = getTableInfo(table)
        if table_info is None:
            return

        # Update the suggested name sufix
        self.counter = self.counter + 1
        query_description = self.getQueryInfo(table_info, table)
        if query_description is None:
            self.counter = self.counter - 1
            return

        # Update the list of names in use for filtered tables
        self.ft_names.append(query_description[u'ft_name'])
        self.last_query = [query_description[u'src_filepath'], 
            query_description[u'src_path'], query_description[u'condition']]

        # Run the query
        tmp_h5file = self.dbt_model.tmp_dbdoc.h5file
        new_query = query.Query(tmp_h5file, table_uid, table, 
            query_description)
        new_query.query_completed.connect(self.addQueryResult)
        QtGui.qApp.setOverrideCursor(QtCore.Qt.WaitCursor)
        new_query.run()


    def getQueryInfo(self, info, table):
        """Retrieves useful info about the query.

        :Parameters:

        - `info`: dictionary with info about the queried table
        - `table`: the tables.Table instance being queried
        """

        # Information about table
        # Setup the initial condition
        last_query = self.last_query
        if (last_query[0], last_query[1]) == \
        (info[u'src_filepath'], info[u'src_path']):
            initial_condition = last_query[2]
        else:
            initial_condition = ''

        # GET THE QUERY COMPONENTS
        # Get a complete query description from user input: condition to
        # be applied, involved range of rows, name of the
        # filtered table and name of the column of returned indices
        query_dlg = queryDlg.QueryDlg(info, self.ft_names, 
            self.counter, initial_condition, table)
        try:
            query_dlg.exec_()
        finally:
            query_description = dict(query_dlg.query_info)
            del query_dlg
            QtGui.qApp.processEvents()

        if not query_description[u'condition']:
            return None

        # SET THE TITLE OF THE RESULT TABLE
        title = query_description[u'condition']
        for name in info[u'valid_fields']:
            # Valid fields can have the format 'fieldname' or 
            # 'varname (name with blanks)' so a single blank shouldn't
            # be used as separator
            components = name.split(u' (')
            if len(components) > 1:
                fieldname = u'(%s' % components[-1]
                title = title.replace(components[0], fieldname)
        query_description[u'title'] = title

        return query_description


    def deleteAllQueries(self):
        """Delete all nodes from the query results tree."""

        title = trs('Cleaning the Query results file', 
            'Caption of the QueryDeleteAll dialog')
        text = trs("""\n\nYou are about to delete all nodes """
                """under Query results\n\n""", 'Ask for confirmation')
        itext = ''
        dtext = ''
        buttons = {\
            'Delete': \
                (trs('Delete', 'Button text'), QtGui.QMessageBox.YesRole), 
            'Cancel': \
                (trs('Cancel', 'Button text'), QtGui.QMessageBox.NoRole), 
            }

        # Ask for confirmation
        answer = vitables.utils.questionBox(title, text, itext, dtext, buttons)
        if answer == 'Cancel':
            return

        # Remove every filtered table from the tree of databases model/view
        model_rows = self.dbt_model.rowCount(QtCore.QModelIndex())
        tmp_index = self.dbt_model.index(model_rows - 1, 0, 
            QtCore.QModelIndex())
        rows_range = range(0, self.dbt_model.rowCount(tmp_index))
        rows_range.reverse()
        for row in rows_range:
            index = self.dbt_model.index(row, 0, tmp_index)
            self.vtapp.nodeDelete(index, force=True)

        # Reset the queries manager
        self.counter = 0
        self.ft_names = []


    def addQueryResult(self, completed, table_uid):
        """Update the GUI once the query has finished.

        Add the result of the query to the tree of databases view and open
        the new filtered table.

        :Parameter table_uid: the UID of the table just queried
        """

        QtGui.qApp.restoreOverrideCursor()
        if not completed:
            print trs('Query on table %s failed!' % table_uid, 
                'Warning log message about a failed query')
            return

        # Update temporary database view i.e. call lazyAddChildren
        model_rows = self.dbt_model.rowCount(QtCore.QModelIndex())
        tmp_index = self.dbt_model.index(model_rows - 1, 0, 
            QtCore.QModelIndex())
        self.dbt_model.lazyAddChildren(tmp_index)

        # The new filtered table is inserted in first position under
        # the Query results node and opened
        index = self.dbt_model.index(0, 0, tmp_index)
        self.vtapp.nodeOpen(index)
