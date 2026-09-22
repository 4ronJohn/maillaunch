@echo off
cd /d D:\Development\maillaunch

maillaunch send --provider gmail --csv test_recipients.csv --subject "Test {{name}}" --body-file test_template.txt --min-delay 1 --max-delay 2 >> task_scheduler.log 2>&1