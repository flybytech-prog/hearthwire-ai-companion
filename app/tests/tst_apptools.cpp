// AppTools (task 012 R4): present()'s one activation per show and the
// token's order and lifetime (P2b), and the About page's values and copy
// (P2c). Offscreen only; no bus (the SingleInstance here is never on one).
#include <QClipboard>
#include <QDBusConnection>
#include <QFile>
#include <QGuiApplication>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QQuickWindow>
#include <QTest>

#include "AppTools.h"
#include "SingleInstance.h"

using Step = AppTools::Step;
using Steps = QList<AppTools::Step>;
Q_DECLARE_METATYPE(Steps)

class TestAppTools : public QObject
{
    Q_OBJECT

private:
    // The environment's token as the window sees it while it is being shown.
    struct ShowProbe {
        QList<QByteArray> seen;
        bool hadToken = false;
    };

    static void watchShow(QQuickWindow &window, ShowProbe &probe)
    {
        QObject::connect(&window, &QWindow::visibleChanged, &window, [&probe](bool visible) {
            if (!visible)
                return;
            probe.hadToken = qEnvironmentVariableIsSet("XDG_ACTIVATION_TOKEN");
            probe.seen.append(qgetenv("XDG_ACTIVATION_TOKEN"));
        }, Qt::DirectConnection);
    }

private Q_SLOTS:
    void init()
    {
        qunsetenv("XDG_ACTIVATION_TOKEN");
    }

    void needsRequestActivate_data()
    {
        QTest::addColumn<bool>("wasVisible");
        QTest::addColumn<bool>("wayland");
        QTest::addColumn<bool>("needed");
        // Wayland activates a hidden window on show (qtbase 6.12.0
        // qwaylandwindow.cpp:656): a second request would be a second activation.
        QTest::newRow("hidden, Wayland: show() activates, no request") << false << true << false;
        QTest::newRow("shown, Wayland: show() doesn't, request") << true << true << true;
        QTest::newRow("hidden, not Wayland: request") << false << false << true;
        QTest::newRow("shown, not Wayland: request") << true << false << true;
    }

    void needsRequestActivate()
    {
        QFETCH(bool, wasVisible);
        QFETCH(bool, wayland);
        QFETCH(bool, needed);
        QCOMPARE(AppTools::needsRequestActivate(wasVisible, wayland), needed);
    }

    void presentSteps_data()
    {
        QTest::addColumn<bool>("token");
        QTest::addColumn<bool>("wasVisible");
        QTest::addColumn<bool>("wayland");
        QTest::addColumn<Steps>("steps");
        const Step S = Step::SetToken, Sh = Step::Show, R = Step::Raise, A = Step::Activate, U = Step::UnsetToken;
        QTest::newRow("token, hidden, Wayland") << true << false << true << Steps{S, Sh, R, U};
        QTest::newRow("token, shown, Wayland") << true << true << true << Steps{S, Sh, R, A, U};
        QTest::newRow("token, hidden, X11") << true << false << false << Steps{S, Sh, R, A, U};
        QTest::newRow("token, shown, X11") << true << true << false << Steps{S, Sh, R, A, U};
        QTest::newRow("no token, hidden, Wayland") << false << false << true << Steps{Sh, R, U};
        QTest::newRow("no token, shown, Wayland") << false << true << true << Steps{Sh, R, A, U};
        QTest::newRow("no token, hidden, X11") << false << false << false << Steps{Sh, R, A, U};
        QTest::newRow("no token, shown, X11") << false << true << false << Steps{Sh, R, A, U};
    }

    void presentSteps()
    {
        QFETCH(bool, token);
        QFETCH(bool, wasVisible);
        QFETCH(bool, wayland);
        QFETCH(Steps, steps);
        const Steps got = AppTools::presentSteps(token, wasVisible, wayland);
        QCOMPARE(got, steps);
        // The rules, independently of the rows: the token before show(), at
        // most one activation request, the environment always cleaned last.
        QCOMPARE(got.count(Step::Activate), AppTools::needsRequestActivate(wasVisible, wayland) ? 1 : 0);
        QCOMPARE(got.last(), Step::UnsetToken);
        if (token)
            QVERIFY(got.indexOf(Step::SetToken) < got.indexOf(Step::Show));
        else
            QVERIFY(!got.contains(Step::SetToken));
    }

    void offscreenIsNotWayland()
    {
        QCOMPARE(QGuiApplication::platformName(), QStringLiteral("offscreen"));
        QVERIFY(!AppTools::platformIsWayland());
    }

    // The real present(): while the window is being shown (where Qt's
    // Wayland plugin reads the variable), the token is already there; after
    // the call it is gone, and SingleInstance has given it up.
    void presentSetsTheTokenBeforeShow()
    {
        SingleInstance instance(QDBusConnection(QStringLiteral("hw-no-bus")));
        instance.Show(QString(), QStringLiteral("hw-test-token.1"));
        QVERIFY(instance.hasToken());
        AppTools tools(nullptr, &instance);
        QQuickWindow window;
        ShowProbe probe;
        watchShow(window, probe);
        tools.present(&window);
        QVERIFY(window.isVisible());
        QCOMPARE(probe.seen.size(), 1);
        QVERIFY(probe.hadToken);
        QCOMPARE(probe.seen.first(), QByteArray("hw-test-token.1"));
        QVERIFY(!qEnvironmentVariableIsSet("XDG_ACTIVATION_TOKEN"));
        QVERIFY(!instance.hasToken());
    }

    // A token the filter refuses never reaches the environment.
    void presentDropsARefusedToken()
    {
        SingleInstance instance(QDBusConnection(QStringLiteral("hw-no-bus")));
        instance.Show(QString(), QStringLiteral("bad token;"));
        AppTools tools(nullptr, &instance);
        QQuickWindow window;
        ShowProbe probe;
        watchShow(window, probe);
        tools.present(&window);
        QCOMPARE(probe.seen.size(), 1);
        QVERIFY(!probe.hadToken);
        QVERIFY(!qEnvironmentVariableIsSet("XDG_ACTIVATION_TOKEN"));
    }

    // Without a token of ours the variable is removed as well (whatever was
    // inherited is never kept past a present()).
    void presentAlwaysUnsets()
    {
        qputenv("XDG_ACTIVATION_TOKEN", "hw-inherited");
        AppTools tools(nullptr, nullptr);
        QQuickWindow window;
        tools.present(&window);
        QVERIFY(window.isVisible());
        QVERIFY(!qEnvironmentVariableIsSet("XDG_ACTIVATION_TOKEN"));
        // A shown window, with a token: still removed afterwards.
        SingleInstance instance(QDBusConnection(QStringLiteral("hw-no-bus")));
        AppTools again(nullptr, &instance);
        instance.Show(QString(), QStringLiteral("hw-test-token.2"));
        again.present(&window);
        QVERIFY(!qEnvironmentVariableIsSet("XDG_ACTIVATION_TOKEN"));
        QVERIFY(!instance.hasToken());
    }

    // review-7 L2: present() called again from a show handler is ignored.
    // The outer call's token is still there after the nested call returns
    // (where Qt's Wayland plugin would read it), the nested call takes no
    // token, and the variable is gone once the outer call ends.
    void presentIgnoresANestedCall()
    {
        SingleInstance instance(QDBusConnection(QStringLiteral("hw-no-bus")));
        instance.Show(QString(), QStringLiteral("hw-test-token.4"));
        AppTools tools(nullptr, &instance);
        QQuickWindow window;
        int nested = 0;
        QObject::connect(&window, &QWindow::visibleChanged, &window, [&](bool visible) {
            if (!visible)
                return;
            ++nested;
            // A second launch's token arrives while the window is shown.
            instance.Show(QString(), QStringLiteral("hw-test-token.5"));
            tools.present(&window);
        }, Qt::DirectConnection);
        ShowProbe probe;
        watchShow(window, probe);
        tools.present(&window);
        QCOMPARE(nested, 1);
        QCOMPARE(probe.seen.size(), 1);
        QVERIFY(probe.hadToken);
        QCOMPARE(probe.seen.first(), QByteArray("hw-test-token.4"));
        QVERIFY(!qEnvironmentVariableIsSet("XDG_ACTIVATION_TOKEN"));
        // The nested call left the newer token for the next present().
        QVERIFY(instance.hasToken());
        tools.present(&window);
        QVERIFY(!instance.hasToken());
        QVERIFY(!qEnvironmentVariableIsSet("XDG_ACTIVATION_TOKEN"));
    }

    void presentIgnoresWhatIsNotAWindow()
    {
        SingleInstance instance(QDBusConnection(QStringLiteral("hw-no-bus")));
        instance.Show(QString(), QStringLiteral("hw-test-token.3"));
        AppTools tools(nullptr, &instance);
        QObject plain;
        tools.present(&plain);
        tools.present(nullptr);
        QVERIFY(!qEnvironmentVariableIsSet("XDG_ACTIVATION_TOKEN"));
    }

    // App.about: exactly plasmoid/metadata.json's values and the .desktop
    // file's Comment.
    void aboutMatchesMetadata()
    {
        QFile metadata(QStringLiteral(HW_METADATA));
        QVERIFY(metadata.open(QIODevice::ReadOnly));
        const QJsonObject plugin = QJsonDocument::fromJson(metadata.readAll()).object().value(QLatin1String("KPlugin")).toObject();
        QVERIFY(!plugin.isEmpty());
        QStringList authors;
        for (const QJsonValue &author : plugin.value(QLatin1String("Authors")).toArray())
            authors << author.toObject().value(QLatin1String("Name")).toString();
        QVERIFY(!authors.isEmpty());

        QFile desktop(QStringLiteral(HW_DESKTOP));
        QVERIFY(desktop.open(QIODevice::ReadOnly | QIODevice::Text));
        QStringList comments;
        for (const QByteArray &line : desktop.readAll().split('\n')) {
            if (line.startsWith("Comment="))
                comments << QString::fromUtf8(line.mid(8));
        }
        QCOMPARE(comments.size(), 1);

        const QVariantMap about = AppTools::about();
        QCOMPARE(about.value(QStringLiteral("name")).toString(), QStringLiteral("Hearthwire"));
        QCOMPARE(about.value(QStringLiteral("appId")).toString(), QStringLiteral("hearthwire-hyprland"));
        QCOMPARE(about.value(QStringLiteral("version")).toString(), QStringLiteral(HW_PROJECT_VERSION));
        QCOMPARE(about.value(QStringLiteral("website")).toString(), plugin.value(QLatin1String("Website")).toString());
        QCOMPARE(about.value(QStringLiteral("bugReportUrl")).toString(), plugin.value(QLatin1String("BugReportUrl")).toString());
        QCOMPARE(about.value(QStringLiteral("license")).toString(), plugin.value(QLatin1String("License")).toString());
        QCOMPARE(about.value(QStringLiteral("authors")).toString(), authors.join(QStringLiteral(", ")));
        QCOMPARE(about.value(QStringLiteral("authorCount")).metaType(), QMetaType::fromType<int>());
        QCOMPARE(about.value(QStringLiteral("authorCount")).toInt(), int(authors.size()));
        QCOMPARE(about.value(QStringLiteral("comment")).toString(), comments.first());
        QCOMPARE(about.value(QStringLiteral("icon")).toString(), QStringLiteral("hearthwire"));
        QCOMPARE(about.keys(), QStringList({QStringLiteral("appId"), QStringLiteral("authorCount"), QStringLiteral("authors"),
                                            QStringLiteral("bugReportUrl"),
                                            QStringLiteral("comment"), QStringLiteral("icon"), QStringLiteral("license"),
                                            QStringLiteral("name"), QStringLiteral("version"), QStringLiteral("website")}));
        for (const char *key : {"website", "bugReportUrl"})
            QVERIFY2(about.value(QLatin1String(key)).toString().startsWith(QLatin1String("https://")), key);
        // The QML property is the same map.
        AppTools tools(nullptr, nullptr);
        QCOMPARE(tools.property("about").toMap(), about);
    }

    void copyAboutCopiesOnlyTheLinks()
    {
        AppTools tools(nullptr, nullptr);
        QClipboard *clipboard = QGuiApplication::clipboard();
        QVERIFY(clipboard);
        clipboard->setText(QStringLiteral("hw-before"));
        for (const char *key : {"comment", "name", "authors", "", "Website", "website "})
            QVERIFY2(!tools.copyAbout(QLatin1String(key)), key);
        QCOMPARE(clipboard->text(), QStringLiteral("hw-before"));
        QVERIFY(tools.copyAbout(QStringLiteral("website")));
        QCOMPARE(clipboard->text(), AppTools::about().value(QStringLiteral("website")).toString());
        QVERIFY(tools.copyAbout(QStringLiteral("bugReportUrl")));
        QCOMPARE(clipboard->text(), AppTools::about().value(QStringLiteral("bugReportUrl")).toString());
        // Not a fixture build: the clipboard isn't read back for QML.
        QCOMPARE(tools.clipboardText(), QString());
    }
};

QTEST_MAIN(TestAppTools)
#include "tst_apptools.moc"
