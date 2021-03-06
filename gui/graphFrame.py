# =============================================================================
# Copyright (C) 2010 Diego Duclos
#
# This file is part of pyfa.
#
# pyfa is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# pyfa is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with pyfa.  If not, see <http://www.gnu.org/licenses/>.
# =============================================================================

import os
import traceback
from itertools import chain

# noinspection PyPackageRequirements
import wx
from logbook import Logger

import gui.display
import gui.globalEvents as GE
import gui.mainFrame
from gui.bitmap_loader import BitmapLoader
from gui.graph import Graph
from service.fit import Fit


pyfalog = Logger(__name__)

try:
    import matplotlib as mpl

    mpl_version = int(mpl.__version__[0]) or -1
    if mpl_version >= 2:
        mpl.use('wxagg')
        mplImported = True
    else:
        mplImported = False
    from matplotlib.patches import Patch

    from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg as Canvas
    from matplotlib.figure import Figure

    graphFrame_enabled = True
    mplImported = True
except ImportError as e:
    pyfalog.warning("Matplotlib failed to import.  Likely missing or incompatible version.")
    mpl_version = -1
    Patch = mpl = Canvas = Figure = None
    graphFrame_enabled = False
    mplImported = False
except Exception:
    # We can get exceptions deep within matplotlib. Catch those.  See GH #1046
    tb = traceback.format_exc()
    pyfalog.critical("Exception when importing Matplotlib. Continuing without importing.")
    pyfalog.critical(tb)
    mpl_version = -1
    Patch = mpl = Canvas = Figure = None
    graphFrame_enabled = False
    mplImported = False


class GraphFrame(wx.Frame):

    def __init__(self, parent, style=wx.DEFAULT_FRAME_STYLE | wx.NO_FULL_REPAINT_ON_RESIZE | wx.FRAME_FLOAT_ON_PARENT):

        global graphFrame_enabled
        global mplImported
        global mpl_version

        self.legendFix = False

        if not graphFrame_enabled:
            pyfalog.warning("Matplotlib is not enabled. Skipping initialization.")
            return

        try:
            cache_dir = mpl._get_cachedir()
        except:
            cache_dir = os.path.expanduser(os.path.join("~", ".matplotlib"))

        cache_file = os.path.join(cache_dir, 'fontList.cache')

        if os.access(cache_dir, os.W_OK | os.X_OK) and os.path.isfile(cache_file):
            # remove matplotlib font cache, see #234
            os.remove(cache_file)
        if not mplImported:
            mpl.use('wxagg')

        graphFrame_enabled = True
        if int(mpl.__version__[0]) < 1:
            pyfalog.warning("pyfa: Found matplotlib version {} - activating OVER9000 workarounds".format(mpl.__version__))
            pyfalog.warning("pyfa: Recommended minimum matplotlib version is 1.0.0")
            self.legendFix = True

        mplImported = True

        wx.Frame.__init__(self, parent, title="pyfa: Graph Generator", style=style, size=(520, 390))

        i = wx.Icon(BitmapLoader.getBitmap("graphs_small", "gui"))
        self.SetIcon(i)
        self.mainFrame = gui.mainFrame.MainFrame.getInstance()
        self.CreateStatusBar()

        self.mainSizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(self.mainSizer)

        sFit = Fit.getInstance()
        fit = sFit.getFit(self.mainFrame.getActiveFit())
        self.fits = [fit] if fit is not None else []
        self.fitList = FitList(self)
        self.fitList.SetMinSize((270, -1))
        self.fitList.fitList.update(self.fits)
        self.targets = []
        # self.targetList = TargetList(self)
        # self.targetList.SetMinSize((270, -1))
        # self.targetList.targetList.update(self.targets)

        self.graphSelection = wx.Choice(self, wx.ID_ANY, style=0)
        self.mainSizer.Add(self.graphSelection, 0, wx.EXPAND)

        self.figure = Figure(figsize=(5, 3), tight_layout={'pad': 1.08})

        rgbtuple = wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNFACE).Get()
        clr = [c / 255. for c in rgbtuple]
        self.figure.set_facecolor(clr)
        self.figure.set_edgecolor(clr)

        self.canvas = Canvas(self, -1, self.figure)
        self.canvas.SetBackgroundColour(wx.Colour(*rgbtuple))

        self.subplot = self.figure.add_subplot(111)
        self.subplot.grid(True)

        self.mainSizer.Add(self.canvas, 1, wx.EXPAND)
        self.mainSizer.Add(wx.StaticLine(self, wx.ID_ANY, wx.DefaultPosition, wx.DefaultSize, wx.LI_HORIZONTAL), 0,
                           wx.EXPAND)

        self.graphCtrlPanel = wx.Panel(self)
        self.mainSizer.Add(self.graphCtrlPanel, 0, wx.EXPAND | wx.ALL, 0)

        self.showY0 = True
        self.selectedY = None
        self.selectedYRbMap = {}

        ctrlPanelSizer = wx.BoxSizer(wx.HORIZONTAL)
        viewOptSizer = wx.BoxSizer(wx.VERTICAL)
        self.showY0Cb = wx.CheckBox(self.graphCtrlPanel, wx.ID_ANY, "Always show Y = 0", wx.DefaultPosition, wx.DefaultSize, 0)
        self.showY0Cb.SetValue(self.showY0)
        self.showY0Cb.Bind(wx.EVT_CHECKBOX, self.OnShowY0Update)
        viewOptSizer.Add(self.showY0Cb, 0, wx.LEFT | wx.TOP | wx.RIGHT | wx.EXPAND, 5)
        self.graphSubselSizer = wx.BoxSizer(wx.VERTICAL)
        viewOptSizer.Add(self.graphSubselSizer, 0, wx.ALL | wx.EXPAND, 5)
        ctrlPanelSizer.Add(viewOptSizer, 0, wx.EXPAND | wx.LEFT | wx.TOP | wx.BOTTOM, 5)
        self.inputsSizer = wx.FlexGridSizer(0, 4, 0, 0)
        self.inputsSizer.AddGrowableCol(1)
        ctrlPanelSizer.Add(self.inputsSizer, 1, wx.EXPAND | wx.RIGHT | wx.TOP | wx.BOTTOM, 5)
        self.graphCtrlPanel.SetSizer(ctrlPanelSizer)

        self.drawTimer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.draw, self.drawTimer)

        for view in Graph.views:
            view = view()
            self.graphSelection.Append(view.name, view)

        self.graphSelection.SetSelection(0)
        self.fields = {}
        self.updateGraphWidgets()
        self.sl1 = wx.StaticLine(self, wx.ID_ANY, wx.DefaultPosition, wx.DefaultSize, wx.LI_HORIZONTAL)
        self.mainSizer.Add(self.sl1, 0, wx.EXPAND)

        fitSizer = wx.BoxSizer(wx.HORIZONTAL)
        fitSizer.Add(self.fitList, 1, wx.EXPAND)
        #fitSizer.Add(self.targetList, 1, wx.EXPAND)

        self.mainSizer.Add(fitSizer, 0, wx.EXPAND)

        self.fitList.fitList.Bind(wx.EVT_LEFT_DCLICK, self.OnLeftDClick)
        self.fitList.fitList.Bind(wx.EVT_CONTEXT_MENU, self.OnContextMenu)
        self.mainFrame.Bind(GE.FIT_CHANGED, self.OnFitChanged)
        self.mainFrame.Bind(GE.FIT_REMOVED, self.OnFitRemoved)
        self.Bind(wx.EVT_CLOSE, self.closeEvent)
        self.Bind(wx.EVT_CHAR_HOOK, self.kbEvent)
        self.Bind(wx.EVT_CHOICE, self.graphChanged)
        from gui.builtinStatsViews.resistancesViewFull import EFFECTIVE_HP_TOGGLED  # Grr crclar gons
        self.mainFrame.Bind(EFFECTIVE_HP_TOGGLED, self.OnEhpToggled)

        self.contextMenu = wx.Menu()
        removeItem = wx.MenuItem(self.contextMenu, 1, 'Remove Fit')
        self.contextMenu.Append(removeItem)
        self.contextMenu.Bind(wx.EVT_MENU, self.ContextMenuHandler, removeItem)

        self.Fit()
        self.SetMinSize(self.GetSize())

    def handleDrag(self, type, fitID):
        if type == "fit":
            self.AppendFitToList(fitID)

    def closeEvent(self, event):
        self.closeWindow()
        event.Skip()

    def kbEvent(self, event):
        keycode = event.GetKeyCode()
        mstate = wx.GetMouseState()
        if keycode == wx.WXK_ESCAPE and mstate.GetModifiers() == wx.MOD_NONE:
            self.closeWindow()
            return
        elif keycode == 65 and mstate.GetModifiers() == wx.MOD_CONTROL:
            self.fitList.fitList.selectAll()
        elif keycode in (wx.WXK_DELETE, wx.WXK_NUMPAD_DELETE) and mstate.GetModifiers() == wx.MOD_NONE:
            self.removeFits(self.getSelectedFits())
        event.Skip()

    def OnContextMenu(self, event):
        if self.getSelectedFits():
            self.PopupMenu(self.contextMenu)

    def ContextMenuHandler(self, event):
        selectedMenuItem = event.GetId()
        if selectedMenuItem == 1:  # Copy was chosen
            fits = self.getSelectedFits()
            self.removeFits(fits)

    def OnEhpToggled(self, event):
        event.Skip()
        view = self.getView()
        if view.redrawOnEffectiveChange:
            view.clearCache()
            self.draw()

    def OnFitChanged(self, event):
        event.Skip()
        view = self.getView()
        view.clearCache(key=event.fitID)
        self.draw()

    def OnFitRemoved(self, event):
        event.Skip()
        fit = next((f for f in self.fits if f.ID == event.fitID), None)
        if fit is not None:
            self.removeFits([fit])

    def graphChanged(self, event):
        self.selectedY = None
        self.updateGraphWidgets()
        event.Skip()

    def closeWindow(self):
        from gui.builtinStatsViews.resistancesViewFull import EFFECTIVE_HP_TOGGLED  # Grr gons
        self.fitList.fitList.Unbind(wx.EVT_LEFT_DCLICK, handler=self.OnLeftDClick)
        self.mainFrame.Unbind(GE.FIT_CHANGED, handler=self.OnFitChanged)
        self.mainFrame.Unbind(GE.FIT_REMOVED, handler=self.OnFitRemoved)
        self.mainFrame.Unbind(EFFECTIVE_HP_TOGGLED, handler=self.OnEhpToggled)
        self.Destroy()

    def getView(self):
        return self.graphSelection.GetClientData(self.graphSelection.GetSelection())

    def getValues(self):
        values = {}
        for fieldHandle, field in self.fields.items():
            values[fieldHandle] = field.GetValue()

        return values

    def OnShowY0Update(self, event):
        event.Skip()
        self.showY0 = self.showY0Cb.GetValue()
        self.draw()

    def OnYTypeUpdate(self, event):
        event.Skip()
        obj = event.GetEventObject()
        formatName = obj.GetLabel()
        self.selectedY = self.selectedYRbMap[formatName]
        self.draw()

    def updateGraphWidgets(self):
        view = self.getView()
        view.clearCache()
        self.graphSubselSizer.Clear()
        self.inputsSizer.Clear()
        for child in self.graphCtrlPanel.Children:
            if child is not self.showY0Cb:
                child.Destroy()
        self.fields.clear()

        # Setup view options
        self.selectedYRbMap.clear()
        if len(view.yDefs) > 1:
            i = 0
            for yAlias, yDef in view.yDefs.items():
                if i == 0:
                    rdo = wx.RadioButton(self.graphCtrlPanel, wx.ID_ANY, yDef.switchLabel, style=wx.RB_GROUP)
                else:
                    rdo = wx.RadioButton(self.graphCtrlPanel, wx.ID_ANY, yDef.switchLabel)
                rdo.Bind(wx.EVT_RADIOBUTTON, self.OnYTypeUpdate)
                if i == (self.selectedY or 0):
                    rdo.SetValue(True)
                self.graphSubselSizer.Add(rdo, 0, wx.ALL | wx.EXPAND, 0)
                self.selectedYRbMap[yDef.switchLabel] = i
                i += 1

        # Setup inputs
        for fieldHandle, fieldDef in (('x', view.xDef), *view.extraInputs.items()):
            textBox = wx.TextCtrl(self.graphCtrlPanel, wx.ID_ANY, style=0)
            self.fields[fieldHandle] = textBox
            textBox.Bind(wx.EVT_TEXT, self.onFieldChanged)
            self.inputsSizer.Add(textBox, 1, wx.EXPAND | wx.ALIGN_CENTER_VERTICAL | wx.ALL, 3)
            if fieldDef.inputDefault is not None:
                inputDefault = fieldDef.inputDefault
                if not isinstance(inputDefault, str):
                    inputDefault = ("%f" % inputDefault).rstrip("0")
                    if inputDefault[-1:] == ".":
                        inputDefault += "0"

                textBox.ChangeValue(inputDefault)

            imgLabelSizer = wx.BoxSizer(wx.HORIZONTAL)
            if fieldDef.inputIconID:
                icon = BitmapLoader.getBitmap(fieldDef.inputIconID, "icons")
                if icon is not None:
                    static = wx.StaticBitmap(self.graphCtrlPanel)
                    static.SetBitmap(icon)
                    imgLabelSizer.Add(static, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 1)

            imgLabelSizer.Add(wx.StaticText(self.graphCtrlPanel, wx.ID_ANY, fieldDef.inputLabel), 0,
                              wx.LEFT | wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 3)
            self.inputsSizer.Add(imgLabelSizer, 0, wx.ALIGN_CENTER_VERTICAL)
        self.Layout()
        self.draw()

    def delayedDraw(self, event=None):
        self.drawTimer.Stop()
        self.drawTimer.Start(Fit.getInstance().serviceFittingOptions["marketSearchDelay"], True)

    def draw(self, event=None):
        global mpl_version

        if event is not None:
            event.Skip()

        self.drawTimer.Stop()

        # todo: FIX THIS, see #1430. draw() is not being unbound properly when the window closes, this is an easy fix,
        # but not a proper solution
        if not self:
            pyfalog.warning("GraphFrame handled event, however GraphFrame no longer exists. Ignoring event")
            return

        values = self.getValues()
        view = self.getView()
        self.subplot.clear()
        self.subplot.grid(True)
        legend = []

        min_y = 0 if self.showY0 else None
        max_y = 0 if self.showY0 else None

        xRange = values['x']
        extraInputs = {ih: values[ih] for ih in view.extraInputs}
        try:
            chosenY = [i for i in view.yDefs.keys()][self.selectedY or 0]
        except IndexError:
            chosenY = [i for i in view.yDefs.keys()][0]

        self.subplot.set(xlabel=view.xDef.axisLabel, ylabel=view.yDefs[chosenY].axisLabel)

        for fit in self.fits:
            try:
                xs, ys = view.getPlotPoints(fit, extraInputs, xRange, 100, chosenY)

                # Figure out min and max Y
                min_y_this = min(ys, default=None)
                if min_y is None:
                    min_y = min_y_this
                elif min_y_this is not None:
                    min_y = min(min_y, min_y_this)
                max_y_this = max(ys, default=None)
                if max_y is None:
                    max_y = max_y_this
                elif max_y_this is not None:
                    max_y = max(max_y, max_y_this)

                self.subplot.plot(xs, ys)
                legend.append('{} ({})'.format(fit.name, fit.ship.item.getShortName()))
            except Exception as ex:
                pyfalog.warning("Invalid values in '{0}'", fit.name)
                self.SetStatusText("Invalid values in '%s'" % fit.name)
                self.canvas.draw()
                return

        y_range = max_y - min_y
        min_y -= y_range * 0.05
        max_y += y_range * 0.05
        if min_y == max_y:
            min_y -= min_y * 0.05
            max_y += min_y * 0.05
        if min_y == max_y:
            min_y -= 5
            max_y += 5
        self.subplot.set_ylim(bottom=min_y, top=max_y)

        if mpl_version < 2:
            if self.legendFix and len(legend) > 0:
                leg = self.subplot.legend(tuple(legend), "upper right", shadow=False)
                for t in leg.get_texts():
                    t.set_fontsize('small')

                for l in leg.get_lines():
                    l.set_linewidth(1)

            elif not self.legendFix and len(legend) > 0:
                leg = self.subplot.legend(tuple(legend), "upper right", shadow=False, frameon=False)
                for t in leg.get_texts():
                    t.set_fontsize('small')

                for l in leg.get_lines():
                    l.set_linewidth(1)
        elif mpl_version >= 2:
            legend2 = []
            legend_colors = {
                0: "blue",
                1: "orange",
                2: "green",
                3: "red",
                4: "purple",
                5: "brown",
                6: "pink",
                7: "grey",
            }

            for i, i_name in enumerate(legend):
                try:
                    selected_color = legend_colors[i]
                except:
                    selected_color = None
                legend2.append(Patch(color=selected_color, label=i_name), )

            if len(legend2) > 0:
                leg = self.subplot.legend(handles=legend2)
                for t in leg.get_texts():
                    t.set_fontsize('small')

                for l in leg.get_lines():
                    l.set_linewidth(1)

        self.canvas.draw()
        self.SetStatusText("")
        self.Refresh()

    def onFieldChanged(self, event):
        view = self.getView()
        view.clearCache()
        self.delayedDraw()

    def AppendFitToList(self, fitID):
        sFit = Fit.getInstance()
        fit = sFit.getFit(fitID)
        if fit not in self.fits:
            self.fits.append(fit)

        self.fitList.fitList.update(self.fits)
        self.draw()

    def OnLeftDClick(self, event):
        row, _ = self.fitList.fitList.HitTest(event.Position)
        if row != -1:
            try:
                fit = self.fits[row]
            except IndexError:
                pass
            else:
                self.removeFits([fit])

    def removeFits(self, fits):
        toRemove = [f for f in fits if f in self.fits]
        if not toRemove:
            return
        for fit in toRemove:
            self.fits.remove(fit)
        self.fitList.fitList.update(self.fits)
        view = self.getView()
        for fit in fits:
            view.clearCache(key=fit.ID)
        self.draw()

    def getSelectedFits(self):
        fits = []
        for row in self.fitList.fitList.getSelectedRows():
            try:
                fit = self.fits[row]
            except IndexError:
                continue
            fits.append(fit)
        return fits


class FitList(wx.Panel):

    def __init__(self, parent):
        wx.Panel.__init__(self, parent)
        self.mainSizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(self.mainSizer)

        self.fitList = FitDisplay(self)
        self.mainSizer.Add(self.fitList, 1, wx.EXPAND)
        fitToolTip = wx.ToolTip("Drag a fit into this list to graph it")
        self.fitList.SetToolTip(fitToolTip)


class FitDisplay(gui.display.Display):
    DEFAULT_COLS = ["Base Icon",
                    "Base Name"]

    def __init__(self, parent):
        gui.display.Display.__init__(self, parent)


class TargetList(wx.Panel):

    def __init__(self, parent):
        wx.Panel.__init__(self, parent)
        self.mainSizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(self.mainSizer)

        self.targetList = TargetDisplay(self)
        self.mainSizer.Add(self.targetList, 1, wx.EXPAND)
        fitToolTip = wx.ToolTip("Drag a fit into this list to graph it")
        self.targetList.SetToolTip(fitToolTip)


class TargetDisplay(gui.display.Display):
    DEFAULT_COLS = ["Base Icon",
                    "Base Name"]

    def __init__(self, parent):
        gui.display.Display.__init__(self, parent)
