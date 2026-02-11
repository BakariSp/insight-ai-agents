from api.conversation import _is_ppt_request
print(_is_ppt_request('生成一个数学课件ppt'))
print(_is_ppt_request('概率统计，DSE，45分钟，公式推到'))
print(_is_ppt_request('USER: 生成一个数学课件ppt\nASSISTANT: ...\n概率统计'))
