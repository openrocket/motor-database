Resource: https://www.thrustcurve.org/info/raspformat.html, accessed on 2025-12-26 at 23:06 UTC.


# RASP File Format

RASP was the original rocket flight simulator, started by the model rocket pioneer G. Harry Stine. This format, named 
"RASP" or "ENG", has become the standard for motor data interchange and most modern flight simulators can use these 
files directly or import them into their own proprietary formats.

RASP was a very simple program and had relatively strict requirements for the format and data values. Modern simulators
are generally more forgiving, but it's still preferable to make your files comply to the original standard to allow them 
to work with as many programs as possible.

For the hard-core, the [source code](http://www.ibiblio.org/pub/archives/rec.models.rockets/RASP/MRASP/mac_raspinfo.c) 
for the RASP engine database listing program is the ultimate authority.

This page gives you enough information to create and edit these files by hand. There is also a tool you can use to trace 
the thrust curve from a graph image and produce RASP data files automatically. See the TCtracer page for more info.

## The Header Line

Blank lines and lines beginning with semicolons are ignored at the begnning of the entry. The first line interpreted is 
the "header line", which contains info on the motor itself. The header contains seven pieces of info, separated by 
spaces. All seven must be present for the entry to be read successfully.

Here's a sample fragment, with a few comments and the header line:

![raspheader.png](raspheader.png)

1. The common name of the motor; just the impulse class and average thrust.
2. The casing diameter in millimeters (mm).
3. The casing length, also in millimeters.
4. The list of available delays, separated by dashes. If the motor has an ejection charge but no delay use "0" and if 
   it has no ejection charge at all use "P" (plugged).
5. The weight of all consumables in the motor. For solid motors this is simply the propellant itself, but for hybrids 
   it is the fuel grain(s) plus the oxidizer (such as N2O). This weight is expressed in kilograms (Kg).
6. The weight of the motor loaded and ready for flight, also in kilograms.
7. The motor manufacturer abbreviated to a few letters. NAR maintains a list of manufacturer abbreviations on page 2 
   of the [combined master list](https://www.nar.org/SandT/pdf/CombinedMotorsByImpulse.pdf).

## Data Points

Starting immediately after the header line, the remaining lines contain sample data points. Each sample specifies a time 
(seconds) and a thrust (Newtons) as two floating-point numbers, usually preceded by a few spaces for readability.

An implicit first point at 0,0 is assumed and should not be specified explicitly. The final point must have a thrust of 
zero and it indicates the motor's burn time. The points should be in increasing order of time and the thrusts should 
trace out the thrust curve as representatively as possible.

After the final data point, the entry may end or contain comments and blank lines, but nothing else.

RASP supported a maximum of 32 data points, including the final (zero) point. This site does not enforce that limitation 
since modern simulator programs don't either. However, files with more than 32 data points will not work with some 
older programs.

It is common to put a single line containing just a semicolon after the sample data. This is not interpreted by the 
software, but it does prevent two entries from running together if multiple entries are present in the same file. Here's 
the first example we created on the [contribute page](https://www.thrustcurve.org/info/contribute.html):

```
; Rocketvision F32
; from NAR data sheet updated 11/2000
; created by John Coker 5/2006
F32 24 124 5-10-15 .0377 .0695 RV
   0.01 50
   0.05 56
   0.10 48
   2.00 24
   2.20 19
   2.24  5
   2.72  0
;
```

## Common Problems

One common problem with RASP data floating around is that the thrust drops to zero before the end of the data. However, 
a sample with zero thrust represents the end of the data. Note that a point at zero time is not required. (It is a 
common mistake to create an initial point at zero time, zero thrust.) This site will detect this problem and reject an 
entry with zero thrust at other than the last point.

The burn always starts at zero time and thus the burn time is simply the time at the final (zero thrust) point. The 
final point must have zero thrust and this site will detect this problem and reject an entry without it.

The data points need not be spaced evenly apart, but they must be in order of time. This site will detect this problem 
and reject an entry where a data point occurs before the previous point (or where the first point occurs in negative 
time).

The original RASP would only read a motor descriptions from a single file (RASP.ENG). All motor entries were located in 
this file, separated by comment lines (beginning with a semicolon). When maintaining multiple motor entries in a single 
file, make sure that each entry is separated by at least one comment line. Since this site is database-oriented, each 
entry is stored in a separate record. This site will parse these multi-motor files and attempt to pick out the correct 
motor.

Finally, a perennial problem is with the manufacturer name. Originally, only a few manufacturers existed and each had a 
single-letter code (E=Estes, A=AeroTech, K=Kosdon, and so on). With the rapid increase in the number of manufacturers, 
this has become impractical. NAR maintains a list of manufacturer abbreviations in the combined master list, but 
unfortunately they aren't used consistently.

This site has collected the abbreviations from the NAR master list and those used by various simulator programs and 
listed them as aliases along with the other manufacturer info (See the Manufacturers page). When scanning simulator 
files, it checks against the full name, abbreviation and the set of aliases to match the manufacturer.
