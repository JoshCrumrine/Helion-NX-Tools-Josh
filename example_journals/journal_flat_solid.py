# NX 2506
# Journal created by jo388c on Wed Nov 11 21:28:01 2026 Pacific Standard Time
#
import math
import NXOpen
import NXOpen.Features
import NXOpen.MenuBar
import NXOpen.Preferences
def main(args) : 

    theSession  = NXOpen.Session.GetSession() #type: NXOpen.Session
    workPart = theSession.Parts.Work
    displayPart = theSession.Parts.Display
    # ----------------------------------------------
    #   Menu: Application->Design->Sheet Metal
    # ----------------------------------------------
    markId1 = theSession.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Enter Sheet Metal")
    
    theSession.ApplicationSwitchImmediate("UG_APP_SBSM")
    
    theUI = NXOpen.UI.GetUI() #type: NXOpen.UI
    
    menuButton1 = theUI.MenuBarManager.GetButtonFromName("UG_PREFERENCES_3D_INPUT_DEVICES")
    
    menuButton1.ButtonSensitivity = NXOpen.MenuBar.MenuButton.SensitivityStatus.Insensitive
    
    menuButton2 = theUI.MenuBarManager.GetButtonFromName("_3DX_BUTTONEDITOR")
    
    menuButton2.ButtonSensitivity = NXOpen.MenuBar.MenuButton.SensitivityStatus.Sensitive
    
    sketch1 = theSession.ActiveSketch
    
    theSession.CleanUpFacetedFacesAndEdges()
    
    # ----------------------------------------------
    #   Menu: Insert->Flat Pattern->Flat Solid...
    # ----------------------------------------------
    markId2 = theSession.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Start")
    
    flatSolidBuilder1 = workPart.Features.SheetmetalManager.CreateFlatSolidFeatureBuilder(NXOpen.Features.Feature.Null)
    
    flatSolidBuilder1.SetApplicationContext(NXOpen.Features.SheetMetal.ApplicationContext.NxSheetMetal)
    
    flatSolidBuilder1.LayerSetting = NXOpen.Features.SheetMetal.FlatSolidBuilder.LayerSettingOption.Preference
    
    flatSolidBuilder1.FlatBodyLayer = 1
    
    flatSolidBuilder1.FlatBodyColor = 189
    
    flatSolidBuilder1.OuterCornerTreatment.Value.SetFormula("0.003937")
    
    flatSolidBuilder1.InnerCornerTreatment.Value.SetFormula("0.003937")
    
    flatSolidBuilder1.FixAtTimestamp = True
    
    theSession.SetUndoMarkName(markId2, "Flat Solid Dialog")
    
    insidecornertreatmenttype1 = workPart.Preferences.SheetMetalPreferences.GetInsideCornerTreatmentType()
    
    cornerTreatmentBuilder1 = flatSolidBuilder1.InnerCornerTreatment
    
    cornerTreatmentBuilder1.TreatmentType = NXOpen.Features.SheetMetal.CornerTreatmentBuilder.CornerTreatmentType.NotSet
    
    expression1 = cornerTreatmentBuilder1.Value
    
    expression2 = workPart.Preferences.SheetMetalPreferences.GetFlatPatternInsideCornerTreatmentValue()
    
    name1 = expression2.Name
    
    expression1.RightHandSide = name1
    
    outsidecornertreatmenttype1 = workPart.Preferences.SheetMetalPreferences.GetOutsideCornerTreatmentType()
    
    cornerTreatmentBuilder2 = flatSolidBuilder1.OuterCornerTreatment
    
    cornerTreatmentBuilder2.TreatmentType = NXOpen.Features.SheetMetal.CornerTreatmentBuilder.CornerTreatmentType.NotSet
    
    expression3 = cornerTreatmentBuilder2.Value
    
    expression4 = workPart.Preferences.SheetMetalPreferences.GetFlatPatternOutsideCornerTreatmentValue()
    
    name2 = expression4.Name
    
    expression3.RightHandSide = name2
    
    sketch2 = theSession.ActiveSketch
    
    sketch3 = theSession.ActiveSketch
    
    thicken1 = workPart.Features.FindObject("THICKEN_SHEET(4)")
    face1 = thicken1.FindObject("FACE 4 {(0.4,-1,0) THICKEN_SHEET(4)}")
    flatSolidBuilder1.StationaryFace.Value = face1
    
    selectFace1 = flatSolidBuilder1.StationaryFace
    
    selectFace1.Value = face1
    
    sketch4 = theSession.ActiveSketch
    
    expression3.SetFormula(name2)
    
    expression1.SetFormula(name1)
    
    markId3 = theSession.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, "Flat Solid")
    
    theSession.DeleteUndoMark(markId3, None)
    
    markId4 = theSession.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, "Flat Solid")
    
    feature1 = flatSolidBuilder1.CommitFeature()
    
    theSession.DeleteUndoMark(markId4, None)
    
    theSession.SetUndoMarkName(markId2, "Flat Solid")
    
    flatSolidBuilder1.Destroy()
    
    sketch5 = theSession.ActiveSketch
    
    theSession.CleanUpFacetedFacesAndEdges()
    
    # ----------------------------------------------
    #   Menu: Tools->Automation->Journal->Stop Recording
    # ----------------------------------------------
    
if __name__ == '__main__':
    main(sys.argv[1:])