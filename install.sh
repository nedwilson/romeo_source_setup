#!/usr/bin/env bash

VERSION=`cat PACKAGE | grep version | awk '{print $2}'`
PACKAGE=`cat PACKAGE | grep file | awk -F': ' '{print $2}' | sed -e 's/\.py//g'`

PKGNAME="${PACKAGE}-${VERSION}.rvpkg"
RVDIR="${HOME}/Library/Application Support/RV"
zip ../$PKGNAME PACKAGE romeo_source_setup.py preferences.py
cp -vf ../$PKGNAME /Volumes/romeo_inhouse/romeo/SHARED/sw_installs
if [ -e "${RVDIR}/Packages" ]; then
    cp -vf ../$PKGNAME "${RVDIR}/Packages"
fi
if [ -e "${RVDIR}/Python" ]; then
    cp -vf *.py "${RVDIR}/Python"
    find "${RVDIR}/Python" -name "*.pyc" -exec rm -f {} \;
fi
# rm -f ../$PKGNAME