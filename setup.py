from setuptools import setup

setup(
    name='python-duvet',
    version='0.1',
    packages=['duvet'],

    author='Alex Stapleton',
    author_email='alexs@prol.etari.at',
    description="""
    A nose plugin that does various things with coverage data.

    Currently it only attempts to detect which tests are effected by your
    changes in git and then re-orders or skips tests that haven't changed.
    """,
    license='LGPLv3',
    url='https://github.com/public/python-duvet',

    install_requires=[
        "GitPython",
        "bzr",
        "nose",
        "coverage"
    ],

    entry_points={
        'nose.plugins.0.10': [
            'duvet = duvet.nose:DuvetCover',
        ]
    }
)
