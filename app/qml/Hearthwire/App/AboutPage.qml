import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import Hearthwire.Compat.Kirigami as Kirigami
import Hearthwire.App

// The settings dialog's last category, About (task 012 R4 P2c). Its values
// are fixed at build time (App.about: plasmoid/metadata.json and the
// .desktop file). It has no settings: no cfg_ properties, so opening it never
// enables Apply and leaving it never asks. The links are text to select or
// copy; the app opens nothing and starts nothing for them (decision-1 Q2:
// only the helper is ever started).
// i18n() is the app's context property (LocalizedContext), which the linter
// can't see.
// qmllint disable unqualified
Item {
    id: page

    property string title
    // App.about; the fixture checks set a copy to see both author labels.
    property var about: App.about

    ScrollView {
        id: scroll
        anchors.fill: parent
        contentWidth: availableWidth

        ColumnLayout {
            width: scroll.availableWidth
            spacing: Kirigami.Units.largeSpacing

            Item {
                Layout.preferredHeight: Kirigami.Units.largeSpacing
            }
            Kirigami.Icon {
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredWidth: Kirigami.Units.iconSizes.huge
                Layout.preferredHeight: Kirigami.Units.iconSizes.huge
                source: page.about.icon
            }
            Kirigami.Heading {
                objectName: "aboutName"
                Layout.alignment: Qt.AlignHCenter
                level: 1
                text: page.about.name
            }
            Label {
                objectName: "aboutAppVersion"
                Layout.alignment: Qt.AlignHCenter
                text: i18n("%1 %2", page.about.appId, page.about.version)
            }
            Label {
                objectName: "aboutComment"
                Layout.alignment: Qt.AlignHCenter
                Layout.maximumWidth: scroll.availableWidth - Kirigami.Units.largeSpacing * 2
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                text: page.about.comment
            }

            GridLayout {
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: Kirigami.Units.largeSpacing
                Layout.maximumWidth: scroll.availableWidth - Kirigami.Units.largeSpacing * 2
                columns: 3
                columnSpacing: Kirigami.Units.largeSpacing
                rowSpacing: Kirigami.Units.smallSpacing

                Label {
                    Layout.alignment: Qt.AlignRight
                    text: i18n("License:")
                }
                Label {
                    objectName: "aboutLicense"
                    Layout.columnSpan: 2
                    text: page.about.license
                }

                // review-7 I2: "Authors:" for more than one (they are joined
                // with ", ").
                Label {
                    objectName: "aboutAuthorsLabel"
                    Layout.alignment: Qt.AlignRight
                    text: i18np("Author:", "Authors:", page.about.authorCount)
                }
                Label {
                    objectName: "aboutAuthors"
                    Layout.columnSpan: 2
                    text: page.about.authors
                }

                Label {
                    Layout.alignment: Qt.AlignRight
                    text: i18n("Website:")
                }
                // Plain text to select; never a link that opens anything.
                TextEdit {
                    objectName: "aboutWebsite"
                    Layout.fillWidth: true
                    readOnly: true
                    selectByMouse: true
                    textFormat: TextEdit.PlainText
                    wrapMode: TextEdit.WrapAnywhere
                    color: Kirigami.Theme.textColor
                    selectionColor: Kirigami.Theme.highlightColor
                    selectedTextColor: Kirigami.Theme.highlightedTextColor
                    text: page.about.website
                }
                Button {
                    objectName: "aboutCopyWebsite"
                    icon.name: "edit-copy"
                    text: i18n("Copy")
                    onClicked: App.copyAbout("website")
                }

                Label {
                    Layout.alignment: Qt.AlignRight
                    text: i18n("Report a bug:")
                }
                TextEdit {
                    objectName: "aboutBugReportUrl"
                    Layout.fillWidth: true
                    readOnly: true
                    selectByMouse: true
                    textFormat: TextEdit.PlainText
                    wrapMode: TextEdit.WrapAnywhere
                    color: Kirigami.Theme.textColor
                    selectionColor: Kirigami.Theme.highlightColor
                    selectedTextColor: Kirigami.Theme.highlightedTextColor
                    text: page.about.bugReportUrl
                }
                Button {
                    objectName: "aboutCopyBugReportUrl"
                    icon.name: "edit-copy"
                    text: i18n("Copy")
                    onClicked: App.copyAbout("bugReportUrl")
                }
            }
        }
    }
}
