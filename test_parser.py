from collector import parse_machine_page

sample = """
<html><body><h3>オススメｅ東京喰種Ｗ</h3>
<h5>0267 番台</h5><p>大当 21回　確変／時短 14回</p><p>最大持玉 22870玉</p>
<h5>0268 番台</h5><p>大当 19回　確変／時短 18回</p><p>最大持玉 43300玉</p>
</body></html>
"""
name, rows = parse_machine_page(sample, "fallback")
assert name == "ｅ東京喰種Ｗ"
assert rows[0]["machine_number"] == "0267"
assert rows[0]["big_hits"] == 21
assert rows[0]["kakuhen_jitan"] == 14
assert rows[0]["max_balls"] == 22870
print("parser test OK")
