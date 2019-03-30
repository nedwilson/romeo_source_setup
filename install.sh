#!/usr/bin/env bash

VERSION=`cat PACKAGE | grep version | awk '{print $2}'`
PACKAGE=`cat PACKAGE | grep file | awk -F': ' '{print $2}' | sed -e 's/\.py//g'`

PKGNAME="${PACKAGE}-${VERSION}.rvpkg"
zip $PKGNAME PACKAGE romeo_source_setup.py preferences.py
cp -vf $PKGNAME /Volumes/romeo_inhouse/romeo/SHARED/sw_installs
if [ -e '/Users/ned/Library/Application Support/RV/Packages' ]; then
    cp -vf $PKGNAME '/Users/ned/Library/Application Support/RV/Packages'
fi
if [ -e '/Users/ned/Library/Application Support/RV/Python' ]; then
    cp -vf *.py '/Users/ned/Library/Application Support/RV/Python'
    find '/Users/ned/Library/Application Support/RV/Python' -name '*.pyc' -exec rm -f {} \;
fi
rm -f $PKGNAME