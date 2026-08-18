import re
data = open('web/data.js', encoding='utf-8').read()
matches = [m.start() for m in re.finditer('stillFishing', data)]
print('stillFishing positions:', matches)
idx = data.find('"TODAY"')
if idx != -1:
    print(data[idx:idx+500])
