import wx
from logbook import Logger

import eos.db
from eos.exception import HandledListActionError
from gui.fitCommands.helpers import restoreCheckedStates, stateLimit
from service.fit import Fit


pyfalog = Logger(__name__)


class CalcAddLocalModuleCommand(wx.Command):

    def __init__(self, fitID, newModInfo, commit=True):
        wx.Command.__init__(self, True, 'Add Module')
        self.fitID = fitID
        self.newModInfo = newModInfo
        self.commit = commit
        self.savedPosition = None
        self.subsystemCmd = None
        self.savedStateCheckChanges = None

    def Do(self):
        pyfalog.debug('Doing addition of local module {} to fit {}'.format(self.newModInfo, self.fitID))
        sFit = Fit.getInstance()
        fit = sFit.getFit(self.fitID)

        newMod = self.newModInfo.toModule(fallbackState=stateLimit(self.newModInfo.itemID))
        if newMod is None:
            return False

        # If subsystem and we need to replace, run the replace command instead and bypass the rest of this command
        if newMod.item.category.name == 'Subsystem':
            for oldMod in fit.modules:
                if oldMod.getModifiedItemAttr('subSystemSlot') == newMod.getModifiedItemAttr('subSystemSlot') and newMod.slot == oldMod.slot:
                    if oldMod.itemID == self.newModInfo.itemID:
                        return False
                    from .localReplace import CalcReplaceLocalModuleCommand
                    self.subsystemCmd = CalcReplaceLocalModuleCommand(
                        fitID=self.fitID,
                        position=fit.modules.index(oldMod),
                        newModInfo=self.newModInfo,
                        commit=False)
                    if not self.subsystemCmd.Do():
                        return False
                    # Need to flush because checkStates sometimes relies on module->fit
                    # relationship via .owner attribute, which is handled by SQLAlchemy
                    eos.db.flush()
                    sFit.recalc(fit)
                    self.savedStateCheckChanges = sFit.checkStates(fit, newMod)
                    if self.commit:
                        eos.db.commit()
                    return True
        if not newMod.fits(fit):
            pyfalog.warning('Module does not fit')
            return False
        try:
            fit.modules.append(newMod)
        except HandledListActionError:
            pyfalog.warning('Failed to append to list')
            if self.commit:
                eos.db.commit()
            return False
        self.savedPosition = fit.modules.index(newMod)
        # Need to flush because checkStates sometimes relies on module->fit
        # relationship via .owner attribute, which is handled by SQLAlchemy
        eos.db.flush()
        sFit.recalc(fit)
        self.savedStateCheckChanges = sFit.checkStates(fit, newMod)
        if self.commit:
            eos.db.commit()
        return True

    def Undo(self):
        pyfalog.debug('Undoing addition of local module {} to fit {}'.format(self.newModInfo, self.fitID))
        # We added a subsystem module, which actually ran the replace command. Run the undo for that guy instead
        if self.subsystemCmd is not None:
            if not self.subsystemCmd.Undo():
                return False
            restoreCheckedStates(Fit.getInstance().getFit(self.fitID), self.savedStateCheckChanges)
            if self.commit:
                eos.db.commit()
            return True
        if self.savedPosition is None:
            return False
        from .localRemove import CalcRemoveLocalModulesCommand
        cmd = CalcRemoveLocalModulesCommand(fitID=self.fitID, positions=[self.savedPosition], commit=False)
        if not cmd.Do():
            return False
        restoreCheckedStates(Fit.getInstance().getFit(self.fitID), self.savedStateCheckChanges)
        if self.commit:
            eos.db.commit()
        return True
