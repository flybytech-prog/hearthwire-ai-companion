// HelperCommand::parse: only the helper, as the plasmoid's JS builders spell
// it, and never anything sh would read differently.
#include <QTest>

#include "HelperCommand.h"

class TestHelperCommand : public QObject
{
    Q_OBJECT

private Q_SLOTS:
    void accepted_data()
    {
        QTest::addColumn<QString>("source");
        QTest::addColumn<QStringList>("arguments");
        QTest::addColumn<QStringList>("environment");
        const QStringList base = {"-P", "-m", "hearthwire"};
        // Every builder shape of plasmoid/contents/ui (RefreshGate, UsageHistory,
        // SettingsBackup, InstallInfo, ChatStorage, PromptLibrary, OllamaChat,
        // configUsage), with the app's applet id.
        QTest::newRow("usage") << "env HEARTHWIRE_RUN=7 python3 -P -m hearthwire --json --providers=claude,codex"
                               << base + QStringList{"--json", "--providers=claude,codex"}
                               << QStringList{"HEARTHWIRE_RUN=7"};
        QTest::newRow("usage, no providers") << "env HEARTHWIRE_RUN=0 python3 -P -m hearthwire --json --providers="
                                             << base + QStringList{"--json", "--providers="}
                                             << QStringList{"HEARTHWIRE_RUN=0"};
        QTest::newRow("detect") << "python3 -P -m hearthwire --detect" << base + QStringList{"--detect"} << QStringList{};
        QTest::newRow("history") << "env HEARTHWIRE_RUN=3 python3 -P -m hearthwire --usage-history record --applet 2147483648 --sample claude.five_hour=40,codex.weekly=100"
                                 << base + QStringList{"--usage-history", "record", "--applet", "2147483648", "--sample", "claude.five_hour=40,codex.weekly=100"}
                                 << QStringList{"HEARTHWIRE_RUN=3"};
        QTest::newRow("install-info -s") << "env HEARTHWIRE_RUN=1 HEARTHWIRE_APPLET=2147483648 python3 -P -s -m hearthwire --install-info"
                                         << QStringList{"-P", "-s", "-m", "hearthwire", "--install-info"}
                                         << QStringList{"HEARTHWIRE_RUN=1", "HEARTHWIRE_APPLET=2147483648"};
        QTest::newRow("owner, quoted address") << "env HEARTHWIRE_RUN=2 HEARTHWIRE_APPLET=2147483648 python3 -P -m hearthwire --port-owner 8080 --address '[fd00::1]'"
                                               << base + QStringList{"--port-owner", "8080", "--address", "[fd00::1]"}
                                               << QStringList{"HEARTHWIRE_RUN=2", "HEARTHWIRE_APPLET=2147483648"};
        QTest::newRow("persona model") << "env HEARTHWIRE_RUN=4 HEARTHWIRE_APPLET=2147483648 python3 -P -m hearthwire --prompts set-persona --model library/llama3.2:3b-q4+x --id 12"
                                       << base + QStringList{"--prompts", "set-persona", "--model", "library/llama3.2:3b-q4+x", "--id", "12"}
                                       << QStringList{"HEARTHWIRE_RUN=4", "HEARTHWIRE_APPLET=2147483648"};
        QTest::newRow("web-data") << "env HEARTHWIRE_RUN=5 HEARTHWIRE_APPLET=2147483648 python3 -P -m hearthwire --web-data prepare --store encrypted --applet 2147483648 --generation 2 --sites claude,user-0a1b2c3d"
                                  << base + QStringList{"--web-data", "prepare", "--store", "encrypted", "--applet", "2147483648", "--generation", "2", "--sites", "claude,user-0a1b2c3d"}
                                  << QStringList{"HEARTHWIRE_RUN=5", "HEARTHWIRE_APPLET=2147483648"};
        QTest::newRow("backup") << "env HEARTHWIRE_RUN=9 python3 -P -m hearthwire --settings-backup export --applet 2147483648"
                                << base + QStringList{"--settings-backup", "export", "--applet", "2147483648"}
                                << QStringList{"HEARTHWIRE_RUN=9"};
    }

    void accepted()
    {
        QFETCH(QString, source);
        QFETCH(QStringList, arguments);
        QFETCH(QStringList, environment);
        const HelperCommand command = HelperCommand::parse(source);
        QVERIFY(command.ok);
        QCOMPARE(command.arguments, arguments);
        QStringList env;
        for (const auto &pair : command.environment)
            env << pair.first + QLatin1Char('=') + pair.second;
        QCOMPARE(env, environment);
    }

    void refused_data()
    {
        QTest::addColumn<QString>("source");
        QTest::newRow("empty") << "";
        QTest::newRow("another program") << "sh -c 'python3 -P -m hearthwire --json'";
        QTest::newRow("absolute python") << "/usr/bin/python3 -P -m hearthwire --json";
        QTest::newRow("another python") << "python3.12 -P -m hearthwire --json";
        QTest::newRow("no -P") << "python3 -m hearthwire --json";
        QTest::newRow("-c") << "python3 -P -c print(1)";
        QTest::newRow("another module") << "python3 -P -m http.server --json";
        QTest::newRow("no helper option") << "python3 -P -m hearthwire";
        QTest::newRow("first not an option") << "python3 -P -m hearthwire json";
        QTest::newRow("front end in env") << "env HEARTHWIRE_FRONTEND=plasma python3 -P -m hearthwire --json";
        QTest::newRow("agents panel in env") << "env HEARTHWIRE_AGENTS_PANEL=1 python3 -P -m hearthwire --json";
        QTest::newRow("other env word") << "env PYTHONPATH=/tmp python3 -P -m hearthwire --json";
        QTest::newRow("env word not digits") << "env HEARTHWIRE_RUN=x python3 -P -m hearthwire --json";
        QTest::newRow("env word empty") << "env HEARTHWIRE_RUN= python3 -P -m hearthwire --json";
        QTest::newRow("env word twice") << "env HEARTHWIRE_RUN=1 HEARTHWIRE_RUN=2 python3 -P -m hearthwire --json";
        QTest::newRow("bare env") << "env python3 -P -m hearthwire --json";
        QTest::newRow("env option") << "env -i python3 -P -m hearthwire --json";
        QTest::newRow("assignment without env") << "HEARTHWIRE_RUN=1 python3 -P -m hearthwire --json";
        QTest::newRow("semicolon") << "python3 -P -m hearthwire --json; touch x";
        QTest::newRow("and") << "python3 -P -m hearthwire --json && touch x";
        QTest::newRow("pipe") << "python3 -P -m hearthwire --json | cat";
        QTest::newRow("redirect") << "python3 -P -m hearthwire --json >x";
        QTest::newRow("dollar") << "python3 -P -m hearthwire --json $HOME";
        QTest::newRow("command substitution") << "python3 -P -m hearthwire --json $(id)";
        QTest::newRow("backticks") << "python3 -P -m hearthwire --json `id`";
        QTest::newRow("glob") << "python3 -P -m hearthwire --json *";
        QTest::newRow("unquoted bracket") << "python3 -P -m hearthwire --address [::1]";
        QTest::newRow("tilde") << "python3 -P -m hearthwire --read ~";
        QTest::newRow("double quotes") << "python3 -P -m hearthwire --address \"x\"";
        QTest::newRow("quote glued to a word") << "python3 -P -m hearthwire --address 'a'b";
        QTest::newRow("word glued to a quote") << "python3 -P -m hearthwire --address a'b'";
        QTest::newRow("open quote") << "python3 -P -m hearthwire --address 'abc";
        QTest::newRow("backslash") << "python3 -P -m hearthwire --a b\\ c";
        QTest::newRow("two spaces") << "python3  -P -m hearthwire --json";
        QTest::newRow("leading space") << " python3 -P -m hearthwire --json";
        QTest::newRow("trailing space") << "python3 -P -m hearthwire --json ";
        QTest::newRow("tab") << "python3\t-P -m hearthwire --json";
        QTest::newRow("newline") << "python3 -P -m hearthwire --json\ntouch x";
        QTest::newRow("newline in quotes") << "python3 -P -m hearthwire --address 'a\nb'";
        QTest::newRow("hash") << "python3 -P -m hearthwire --json #x";
        QTest::newRow("non-ASCII") << QString::fromUtf8("python3 -P -m hearthwire --json \xc3\xa9");
        QTest::newRow("too long") << "python3 -P -m hearthwire --read-dropped " + QString(HelperCommand::MaxLength, QLatin1Char('a'));
        QString many = QStringLiteral("python3 -P -m hearthwire --json");
        for (int i = 0; i < HelperCommand::MaxWords; ++i)
            many += QStringLiteral(" x");
        QTest::newRow("too many words") << many;
    }

    void refused()
    {
        QFETCH(QString, source);
        const HelperCommand command = HelperCommand::parse(source);
        QVERIFY(!command.ok);
        QVERIFY(command.arguments.isEmpty());
        QVERIFY(command.environment.isEmpty());
    }

    void longestHexPathFits()
    {
        // PromptLibrary.MAX_HEX is 8192.
        const QString source = "env HEARTHWIRE_RUN=1 HEARTHWIRE_APPLET=2147483648 python3 -P -m hearthwire --read-dropped "
            + QString(8192, QLatin1Char('a'));
        QVERIFY(HelperCommand::parse(source).ok);
    }
};

QTEST_GUILESS_MAIN(TestHelperCommand)
#include "tst_helpercommand.moc"
