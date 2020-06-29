FROM debian:buster
RUN apt-get update && apt-get -y dist-upgrade && apt-get -y install chromium chromium-driver python3-selenium python3-requests
ADD amexcrawler.py /bin/
ADD sebcardcrawler.py /bin/
