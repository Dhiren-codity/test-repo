RSpec.describe PolyglotAPI do
  include Rack::Test::Methods

  def app
    PolyglotAPI
  end

  describe 'GET /health' do
    it 'returns healthy status' do
      get '/health'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['status']).to eq('healthy')
    end
  end

  describe 'POST /analyze' do
    it 'accepts valid content' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'language' => 'python', 'lines' => ['def test'] })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .and_return({ 'score' => 85.0, 'issues' => [] })

      post '/analyze', { content: 'def test(): pass', path: 'test.py' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response).to have_key('summary')
    end
  end

  describe 'GET /status' do
    it 'returns health status for services' do
      go_url = "#{app.settings.go_service_url}/health"
      py_url = "#{app.settings.python_service_url}/health"
      allow(HTTParty).to receive(:get).with(go_url, timeout: 2).and_return(double(code: 200))
      allow(HTTParty).to receive(:get).with(py_url, timeout: 2).and_return(double(code: 500))

      get '/status'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['services']['ruby']['status']).to eq('healthy')
      expect(json_response['services']['go']['status']).to eq('healthy')
      expect(json_response['services']['python']['status']).to eq('unhealthy')
    end

    it 'marks services unreachable on exception' do
      allow(HTTParty).to receive(:get).and_raise(StandardError.new('timeout'))

      get '/status'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['services']['go']['status']).to eq('unreachable')
      expect(json_response['services']['python']['status']).to eq('unreachable')
    end
  end

  describe 'POST /analyze validations and language detection' do
    it 'returns 422 on validation errors with details' do
      error_obj = double(to_hash: { field: 'content', message: 'is required' })
      allow(RequestValidator).to receive(:validate_analyze_request).and_return([error_obj])

      post '/analyze', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(422)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Validation failed')
      expect(json_response['details']).to include({ 'field' => 'content', 'message' => 'is required' })
    end

    it 'detects language from path and passes to python service' do
      allow(RequestValidator).to receive(:validate_analyze_request).and_return([])
      expect_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/parse', hash_including(content: 'puts 1', path: 'file.rb'), anything)
        .and_return({ 'language' => 'ruby', 'lines' => ['puts 1'] })

      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service) do |_, endpoint, data, _|
        expect(endpoint).to eq('/review')
        expect(data).to include(content: 'puts 1', language: 'ruby')
      end.and_return({ 'score' => 90, 'issues' => [] })

      post '/analyze', { content: 'puts 1', path: 'file.rb' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['summary']['language']).to eq('ruby')
    end
  end

  describe 'POST /diff' do
    it 'returns 400 when old_content or new_content missing' do
      post '/diff', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      body = JSON.parse(last_response.body)
      expect(body['error']).to eq('Missing old_content or new_content')
    end

    it 'returns diff and new code review on success' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/diff', hash_including(old_content: 'a', new_content: 'b'))
        .and_return({ 'changes' => 1, 'patch' => '@@ -1 +1 @@' })

      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'b'))
        .and_return({ 'score' => 75, 'issues' => ['nit'] })

      post '/diff', { old_content: 'a', new_content: 'b' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['diff']).to include('changes' => 1)
      expect(body['new_code_review']).to include('score' => 75)
    end
  end

  describe 'POST /metrics' do
    it 'returns 400 when content missing' do
      post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      body = JSON.parse(last_response.body)
      expect(body['error']).to eq('Missing content')
    end

    it 'returns metrics, review, and overall_quality' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/metrics', hash_including(content: 'code'))
        .and_return({ 'complexity' => 1 })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'code'))
        .and_return({ 'score' => 90, 'issues' => ['one'] })

      post '/metrics', { content: 'code' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['metrics']).to include('complexity' => 1)
      expect(body['review']).to include('score' => 90)
      expect(body['overall_quality']).to eq(30.0)
    end

    it 'returns overall_quality 0.0 when services return error' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'error' => 'timeout' })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .and_return({ 'error' => 'timeout' })

      post '/metrics', { content: 'x' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['overall_quality']).to eq(0.0)
    end
  end

  describe 'POST /dashboard' do
    it 'returns 400 when files array missing or empty' do
      post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      body = JSON.parse(last_response.body)
      expect(body['error']).to eq('Missing files array')
    end

    it 'returns statistics and summary with health score' do
      files = [{ 'path' => 'a.rb', 'content' => 'puts 1' }, { 'path' => 'b.py', 'content' => 'print(1)' }]
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/statistics', hash_including(files: files))
        .and_return({ 'total_files' => 4, 'total_lines' => 100, 'languages' => { 'ruby' => 2 } })

      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/statistics', hash_including(files: files))
        .and_return({ 'average_score' => 80, 'total_issues' => 6, 'average_complexity' => 0.5 })

      post '/dashboard', { files: files }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body).to have_key('timestamp')
      expect(body['file_statistics']['total_files']).to eq(4)
      expect(body['review_statistics']['average_score']).to eq(80)
      expect(body['summary']['health_score']).to eq(62.0)
      expect(body['summary']['total_files']).to eq(4)
      expect(body['summary']['total_lines']).to eq(100)
    end
  end

  describe 'GET /traces' do
    it 'returns total traces and list' do
      allow(CorrelationIdMiddleware).to receive(:all_traces).and_return([{ 'id' => 'abc' }, { 'id' => 'def' }])
      get '/traces'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['total_traces']).to eq(2)
      expect(body['traces'].size).to eq(2)
    end
  end

  describe 'GET /traces/:correlation_id' do
    it 'returns traces for a given correlation id' do
      allow(CorrelationIdMiddleware).to receive(:get_traces).with('xyz').and_return([{ 'step' => 'start' },
                                                                                     { 'step' => 'end' }])
      get '/traces/xyz'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['correlation_id']).to eq('xyz')
      expect(body['trace_count']).to eq(2)
      expect(body['traces'].size).to eq(2)
    end

    it 'returns 404 when no traces found' do
      allow(CorrelationIdMiddleware).to receive(:get_traces).with('none').and_return([])
      get '/traces/none'
      expect(last_response.status).to eq(404)
      body = JSON.parse(last_response.body)
      expect(body['error']).to eq('No traces found for correlation ID')
    end
  end

  describe 'validation errors endpoints' do
    it 'GET /validation/errors returns errors' do
      allow(RequestValidator).to receive(:get_validation_errors).and_return([{ 'field' => 'content',
                                                                               'message' => 'invalid' }])
      get '/validation/errors'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['total_errors']).to eq(1)
      expect(body['errors'].first['field']).to eq('content')
    end

    it 'DELETE /validation/errors clears errors' do
      expect(RequestValidator).to receive(:clear_validation_errors)
      delete '/validation/errors'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['message']).to eq('Validation errors cleared')
    end
  end
end
