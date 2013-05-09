from setuptools import setup

setup(
    name='Duvet Cover',
    packages=['duvet'],

    entry_points={
        'nose.plugins.0.10': [
            'duvet = duvet.nose:DuvetCover'
        ]
    }
)
